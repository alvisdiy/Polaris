"""CountryExplorationEngine — the ONE canonical orchestrator.

Lifecycle (see docs/v0.1/country-exploration-specification.md §5):

  initialize run → load config → generate queries → execute surfaces →
  persist candidates → [claim → analyze → classify → resolve → authority →
  verify → register source → discover scholarships → acquire → expand links
  → record outcome] until bounds/frontier conditions → finalize run

Principle: BROAD DISCOVERY → CAUTIOUS RESOLUTION → STRICT VERIFICATION.
Discovery candidates are rarely rejected; verification is strict.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from loguru import logger
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models.country import Country
from database.models.discovery_frontier import (
    CandidateOrigin,
    CandidateType,
    DiscoveryFrontier,
    FrontierState,
)
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_service import AcquisitionService, AcquisitionMetrics
from services.exploration.authority_source_resolver import (
    AUTHORITY_CANDIDATES_FOUND,
    AUTHORITY_RESOLVED,
    AUTHORITY_UNRESOLVED,
    AuthoritySourceResolver,
)
from services.exploration.candidate_analyzer import AnalyzedCandidate, CandidateAnalyzer
from services.exploration.config_loader import CountryExplorationConfig
from services.exploration.opportunity_classifier import ClassificationResult, OpportunityClassifier
from services.exploration.provider_resolver import ProviderResolver
from services.exploration.query_generation import QueryGenerator
from services.exploration.repositories.frontier_repository import (
    FrontierBounds,
    FrontierObservation,
    FrontierRepository,
)
from services.exploration.repositories.run_repository import RunRepository
from services.exploration.search.base import SearchProvider
from services.exploration.search.counting import CountingSearchProvider
from services.exploration.url_utils import domain_of
from services.exploration.verification_engine import (
    STATE_VERIFIED,
    VerificationEngine,
)

if TYPE_CHECKING:
    from database.models.provider import Provider


class ExplorationMetrics:
    """Aggregated run counters (reported honestly, never asserted)."""

    def __init__(self) -> None:
        self.queries_executed = 0
        self.discovery_queries = 0
        self.queries_failed = 0
        self.search_results = 0
        self.candidates_created = 0
        self.dedup_merges = 0
        self.candidates_by_origin: dict[str, int] = {}
        self.candidates_by_type: dict[str, int] = {}
        self.pages_fetched = 0
        self.fetch_failures = 0
        self.classification_labels: dict[str, int] = {}
        self.jobs_rejected = 0
        self.opportunities_retained = 0
        self.providers_created = 0
        self.providers_resolved = 0
        self.providers_needs_review = 0
        self.authority_resolved = 0
        self.authority_candidates_found = 0
        self.authority_unresolved = 0
        self.sources_verified = 0
        self.sources_needs_review = 0
        self.scholarships_persisted = 0
        self.extraction_failures = 0
        self.duplicates_collapsed = 0
        self.link_expansions = 0
        self.retries = 0
        self.provenance_samples: list[dict] = []

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class CountryExplorationEngine:
    """Explores one country's scholarship ecosystem within explicit bounds."""

    def __init__(
        self,
        session: Session,
        config: CountryExplorationConfig,
        search_provider: SearchProvider,
        analyzer: CandidateAnalyzer | None = None,
    ) -> None:
        self.session = session
        self.config = config
        # Every search call (discovery + authority resolution) goes through
        # the counter, so `queries_executed` is the true backend call count.
        self.search_provider = CountingSearchProvider(search_provider)

        self.country = (
            session.query(Country).filter(Country.iso2 == config.iso2.upper()).first()
        )
        if self.country is None:
            raise ValueError(
                f"Country '{config.iso2}' not found in database. "
                "Seed reference data before exploration."
            )

        self.bounds = FrontierBounds(
            max_candidates=config.bounds.max_candidates,
            max_pages_per_domain=config.bounds.max_pages_per_domain,
            max_depth=config.bounds.max_depth,
        )
        self.frontier = FrontierRepository(session, self.bounds)
        self.run_repo = RunRepository(session)
        self.queries = QueryGenerator(config)
        self.analyzer = analyzer or CandidateAnalyzer(
            per_domain_delay_ms=config.rate_limits.per_domain_delay_ms,
            timeout=config.rate_limits.fetch_timeout_seconds,
        )
        self.classifier = OpportunityClassifier(config.terminology)
        self.provider_resolver = ProviderResolver(
            session, self.country.country_id, config.soft_domain_signals
        )
        self.authority_resolver = AuthoritySourceResolver(
            self.search_provider, config.soft_domain_signals
        )
        self.verifier = VerificationEngine(
            soft_domain_signals=config.soft_domain_signals,
            auto_verify_threshold=config.routing.high_confidence,
            review_threshold=config.routing.medium_confidence,
        )
        self.acquisition = AcquisitionService(session, self.analyzer)
        self.metrics = ExplorationMetrics()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def run(self) -> ExplorationMetrics:
        started = time.monotonic()
        deadline = started + self.config.bounds.max_runtime_minutes * 60

        # Any RUNNING row for this country is from a dead process (killed run,
        # crashed test) — close it out so RUNNING never persists silently.
        stale = self.run_repo.fail_stale_running(
            self.country.country_id, "run interrupted; finalized by a later run start"
        )
        if stale:
            logger.warning("Finalized {} stale RUNNING run(s) for {}", stale, self.config.iso2)

        run = self.run_repo.start_run(
            self.country.country_id,
            config=self.config.model_dump(),
            bounds=self.config.bounds.model_dump(),
        )
        # Captured immediately: after a poisoned session the ORM attribute
        # would need a lazy load, which is exactly what turns a caught
        # pipeline error into a fatal PendingRollbackError (observed in the
        # first live run — the degradation handler crashed on run.run_id).
        run_id = run.run_id
        logger.info("=== Exploration run {} for {} ===", run_id, self.config.iso2)

        try:
            await self._seed_frontier(run_id)
            await self._frontier_loop(run_id, deadline)
            status = "completed"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Exploration run failed: {}", exc)
            status = "failed"
            self._record_run_degradation(run_id, str(exc))

        # True backend totals: the surface reports its own share, authority
        # resolution adds more queries on the same provider. Without this the
        # two numbers disagree with what the search backend actually served.
        self.metrics.queries_executed = self.search_provider.calls
        self.metrics.queries_failed = self.search_provider.failures
        # Read the new-candidate distributions back from persisted state. They
        # were declared but never filled, so every report printed empty dicts.
        self.metrics.candidates_by_origin = self._created_distribution(
            DiscoveryFrontier.origin, run.run_id
        )
        self.metrics.candidates_by_type = self._created_distribution(
            DiscoveryFrontier.candidate_type, run.run_id
        )
        # The repo counter is the real merge record; the metrics field stayed
        # 0 forever because nothing ever copied it across.
        self.metrics.dedup_merges = self.frontier.dedup_merges

        self.metrics_dict = {**self.metrics.to_dict(), **getattr(self, "metrics_dict", {})}
        self.metrics_dict["runtime_seconds"] = round(time.monotonic() - started, 1)
        self.run_repo.finish_run(run, status, self.metrics_dict)
        self.session.commit()
        logger.info(
            "Run {} {}: {} candidates created, {} sources verified, {} scholarships",
            run.run_id, status, self.metrics.candidates_created,
            self.metrics.sources_verified, self.metrics.scholarships_persisted,
        )
        return self.metrics

    def _created_distribution(self, column, run_id: UUID) -> dict[str, int]:
        """Frontier rows created by this run, grouped by one column."""
        rows = (
            self.session.query(column, func.count())
            .filter(
                DiscoveryFrontier.country_id == self.country.country_id,
                DiscoveryFrontier.run_id == run_id,
            )
            .group_by(column)
            .all()
        )
        return {str(value): int(count) for value, count in rows}

    # ------------------------------------------------------------------
    # Step 4-5: surfaces + persistence
    # ------------------------------------------------------------------

    async def _seed_frontier(self, run_id: UUID) -> None:
        """Execute discovery surfaces: web search (primary), seeds, known sources."""
        from services.exploration.surfaces.web_search import WebSearchSurface

        plan = self.queries.generate_plan(run_offset=int(datetime.now(timezone.utc).timestamp()) % 7)
        surface = WebSearchSurface(self.search_provider)
        outcome = await surface.execute(
            plan,
            self.country.country_id,
            self.config.iso2,
            self.config.search_locale,
            self.config.search_gl,
            self.frontier,
            run_id=run_id,
        )
        self.metrics.queries_executed += outcome.queries_executed
        self.metrics.discovery_queries += outcome.queries_executed
        self.metrics.search_results += outcome.results_received
        self.metrics.candidates_created += outcome.candidates_created
        if outcome.degraded_reason:
            self.metrics_dict_degraded = outcome.degraded_reason
            logger.warning("WebSearchSurface degraded: {}", outcome.degraded_reason)

        # Seed URLs from config (optional accelerator)
        for url in self.config.seed_urls:
            _, created = self.frontier.upsert_candidate(
                self.country.country_id,
                url,
                origin=CandidateOrigin.SEED,
                candidate_type=CandidateType.SOURCE,
                observation=FrontierObservation(origin="seed", run_id=str(run_id)),
                priority=1,
                run_id=run_id,
            )
            if created:
                self.metrics.candidates_created += 1

        # Known sources: re-enqueue verified sources for refresh/expansion (Path D)
        known = (
            self.session.query(SourceRegistry)
            .filter(
                SourceRegistry.country_id == self.country.country_id,
                SourceRegistry.status.in_(["Active", "Provisional"]),
            )
            .limit(20)
            .all()
        )
        for source in known:
            _, created = self.frontier.upsert_candidate(
                self.country.country_id,
                source.crawl_entry_url or source.official_url,
                origin=CandidateOrigin.KNOWN_SOURCE,
                candidate_type=CandidateType.SOURCE,
                origin_source_id=source.source_id,
                observation=FrontierObservation(origin="known_source", run_id=str(run_id)),
                priority=2,
                run_id=run_id,
            )
            if created:
                self.metrics.candidates_created += 1

        self.session.commit()

    # ------------------------------------------------------------------
    # The bounded frontier loop
    # ------------------------------------------------------------------

    async def _frontier_loop(self, run_id: UUID, deadline: float) -> None:
        pages_processed = 0
        max_pages = self.config.bounds.max_pages

        while pages_processed < max_pages and time.monotonic() < deadline:
            if self.frontier.count_pending(self.country.country_id) == 0:
                # Drain check: retries may still be pending in the future
                pending_total = (
                    self.session.query(DiscoveryFrontier)
                    .filter(
                        DiscoveryFrontier.country_id == self.country.country_id,
                        DiscoveryFrontier.state == FrontierState.PENDING,
                    )
                    .count()
                )
                if pending_total == 0:
                    break
                # All remaining are future retries — wait briefly or stop early
                break

            candidate = self.frontier.claim_next(self.country.country_id)
            if candidate is None:
                break

            try:
                await self._process_candidate(candidate, run_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Candidate {} processing error: {}", candidate.url, exc)
                # A failed flush poisons the session; recover the transaction
                # before any further SQL (mark_failed_transient included).
                self.session.rollback()
                retried = self.frontier.mark_failed_transient(
                    candidate, str(exc), self.config.bounds.max_retries
                )
                if retried:
                    self.metrics.retries += 1

            pages_processed += 1
            if pages_processed % 5 == 0:
                self.session.commit()

        self.session.commit()

    # ------------------------------------------------------------------
    # Steps 7-16: one candidate through the pipeline
    # ------------------------------------------------------------------

    async def _process_candidate(self, candidate: DiscoveryFrontier, run_id: UUID) -> None:
        # ---- 7. FETCH / ANALYZE (broad discovery: analyze first) ----
        analyzed = await self.analyzer.analyze(candidate.url)
        if not analyzed.fetched:
            error = analyzed.error or "unknown fetch failure"
            if self._is_permanent_fetch_error(error):
                self.frontier.mark_rejected(
                    candidate,
                    {"fetch": error, "reason": "permanently unfetchable"},
                )
                self.metrics.fetch_failures += 1
                return
            retried = self.frontier.mark_failed_transient(
                candidate, error, self.config.bounds.max_retries
            )
            if retried:
                self.metrics.retries += 1
            else:
                self.metrics.fetch_failures += 1
            return

        self.metrics.pages_fetched += 1
        domain = domain_of(analyzed.final_url or analyzed.url)
        self.bounds.processed_domains[domain] = self.bounds.processed_domains.get(domain, 0) + 1

        snippet = self._first_snippet(candidate)
        # ---- 8. CLASSIFY (router, not gate) ----
        classification = self.classifier.classify(analyzed, snippet=snippet)
        self._record_classification(classification, candidate)

        page_hints = [link.url for link in analyzed.links[:30]]

        # ---- 9-12: type-aware handling ----
        if classification.routing == "irrelevant":
            self.frontier.mark_rejected(candidate, self._outcome(analyzed, classification, {"reason": "irrelevant"}))
            return

        if classification.label in ("JOB", "VISA_JOB") and classification.routing == "reject":
            self.metrics.jobs_rejected += 1
            self.frontier.mark_rejected(candidate, self._outcome(analyzed, classification, {"reason": "employment page"}))
            return

        # Scholarship-family, review, unknown → all retained (broad discovery)
        provider: Provider | None = None
        resolution_outcome: dict = {}

        if classification.label in ("SCHOLARSHIP", "FELLOWSHIP", "GRANT", "STUDENT_FUNDING") or (
            classification.routing in ("review", "low_priority")
            and candidate.candidate_type in (CandidateType.OPPORTUNITY, CandidateType.UNKNOWN)
        ):
            org_name, org_conf = self.provider_resolver.extract_org_identity(analyzed)
            resolution = self.provider_resolver.resolve(
                org_name,
                analyzed.final_url or analyzed.url,
                page_title=analyzed.title,
                evidence={
                    "via": candidate.origin,
                    "query": candidate.origin_query,
                    "classification": classification.label,
                    "confidence": classification.confidence,
                },
            )
            provider = resolution.provider
            if resolution.created:
                self.metrics.providers_created += 1
            else:
                self.metrics.providers_resolved += 1
            if resolution.needs_review:
                self.metrics.providers_needs_review += 1

            # ---- 10. AUTHORITY RESOLUTION (never a hard gate) ----
            if classification.label in ("SCHOLARSHIP", "FELLOWSHIP", "GRANT", "STUDENT_FUNDING"):
                authority = await self.authority_resolver.resolve(
                    org_name,
                    domain_of(provider.official_url or "") if provider else None,
                    scholarship_term=self._scholarship_term_for(),
                    page_hints=page_hints,
                )
                if authority.status == AUTHORITY_RESOLVED:
                    self.metrics.authority_resolved += 1
                elif authority.status == AUTHORITY_CANDIDATES_FOUND:
                    self.metrics.authority_candidates_found += 1
                elif authority.status == AUTHORITY_UNRESOLVED:
                    self.metrics.authority_unresolved += 1

                resolution_outcome["authority"] = {
                    "status": authority.status,
                    "provider_domain": authority.provider_domain,
                    "candidates": [
                        {"url": c.url, "score": c.score} for c in authority.candidates[:3]
                    ],
                }

                # Enqueue authority candidates as SOURCE candidates
                for ac in authority.candidates[:3]:
                    _, created = self.frontier.upsert_candidate(
                        self.country.country_id,
                        ac.url,
                        origin=CandidateOrigin.LINK_EXPANSION,
                        candidate_type=CandidateType.SOURCE,
                        origin_url=candidate.url,
                        origin_source_id=None,
                        depth=candidate.depth + 1,
                        priority=2,
                        observation=FrontierObservation(
                            origin="authority_resolution",
                            source_url=candidate.url,
                            run_id=str(run_id),
                            anchor_text=f"authority candidate ({ac.score})",
                        ),
                        run_id=run_id,
                    )
                    if created:
                        self.metrics.candidates_created += 1

        # ---- 12. SOURCE VERIFICATION + REGISTRATION (strict boundary) ----
        # Candidate SOURCE-type pages (and pages with institutional signals)
        # go through verification; accepted ones become SourceRegistry rows.
        if candidate.candidate_type == CandidateType.SOURCE or classification.label in (
            "SCHOLARSHIP", "FELLOWSHIP", "GRANT", "STUDENT_FUNDING"
        ):
            verdict = self.verifier.verify_source(
                analyzed.final_url or analyzed.url,
                https_ok=(analyzed.final_url or analyzed.url).lower().startswith("https://"),
                reachable=True,
                org_identity_match=bool(provider) and resolution_outcome.get("authority", {}).get(
                    "provider_domain"
                ) == domain_of(analyzed.final_url or analyzed.url),
                provider_name=provider.provider_name if provider else "",
                scholarship_content=classification.label in (
                    "SCHOLARSHIP", "FELLOWSHIP", "GRANT", "STUDENT_FUNDING"
                ),
                structured_data=bool(analyzed.structured_data),
                referenced_by_verified=False,
                title=analyzed.title,
            )
            resolution_outcome["verification"] = {
                "state": verdict.state,
                "confidence": verdict.confidence,
                "signals": verdict.signals,
            }
            if verdict.state == STATE_VERIFIED:
                self._register_source(candidate, analyzed, provider, verdict, run_id)

        # ---- 13-14. SCHOLARSHIP ACQUISITION from verified sources ----
        if candidate.candidate_type == CandidateType.SOURCE:
            source = self._source_for_candidate(candidate)
            if source is not None:
                acq = await self.acquisition.acquire_from_source(source)
                self.metrics.scholarships_persisted += acq.scholarships_persisted
                self.metrics.extraction_failures += acq.extraction_failed
                self.metrics.duplicates_collapsed += acq.duplicates_collapsed
                resolution_outcome["acquisition"] = {
                    "urls": acq.scholarship_urls_found,
                    "fetched": acq.pages_fetched,
                    "persisted": acq.scholarships_persisted,
                }

        # ---- 15. LINK EXPANSION (bounded, prioritized) ----
        expanded = self._expand_links(candidate, analyzed, classification, run_id)
        self.metrics.link_expansions += expanded
        # Expanded links are new frontier candidates like any other; leaving
        # them out made candidates_created disagree with the frontier.
        self.metrics.candidates_created += expanded

        # ---- 16. RECORD OUTCOME (candidate stays in frontier history) ----
        outcome = self._outcome(analyzed, classification, resolution_outcome)
        self.frontier.mark_done(candidate, outcome)
        self._sample_provenance(candidate, classification)

    # ------------------------------------------------------------------
    # Steps 12-14: source registration + acquisition
    # ------------------------------------------------------------------

    def _register_source(
        self,
        candidate: DiscoveryFrontier,
        analyzed: AnalyzedCandidate,
        provider: "Provider | None",
        verdict,
        run_id: UUID,
    ) -> None:
        """Register a verified authoritative source in SourceRegistry.

        Idempotent on both unique keys (official_url, crawl_entry_url): the
        first live JP run crashed here because a second candidate pointing at
        the same site tried to INSERT a duplicate crawl_entry_url.
        """
        from database.models.source_registry import SourceRegistry as SR

        url = analyzed.final_url or analyzed.url
        existing = (
            self.session.query(SR)
            .filter(
                (SR.official_url == url) | (SR.crawl_entry_url == url)
            )
            .first()
        )
        if existing is not None:
            existing.verification_state = STATE_VERIFIED
            existing.confidence = verdict.confidence
            self.session.flush()
            return

        source = SR(
            source_name=(analyzed.title or url)[:255],
            country_id=self.country.country_id,
            provider_id=provider.provider_id if provider else None,
            official_url=url[:2048],
            crawl_entry_url=url[:2048],
            crawl_method="Playwright",
            connector_name="generic_playwright",
            crawl_frequency="monthly",
            priority=3,
            robots_allowed=True,
            requires_login=False,
            status="Active",
            verification_state=STATE_VERIFIED,
            confidence=verdict.confidence,
            discovered_via={
                "frontier_candidate": str(candidate.candidate_id),
                "origin": candidate.origin,
                "origin_query": candidate.origin_query,
                "run_id": str(run_id),
                "signals": verdict.signals,
            },
        )
        self.session.add(source)
        try:
            self.session.flush()
        except IntegrityError:
            # A different candidate registered the same site mid-run (the
            # pre-flush SELECT cannot see rows another flush added since our
            # last read). Roll back the poisoned insert, reuse that row.
            self.session.rollback()
            existing = (
                self.session.query(SR)
                .filter((SR.official_url == url) | (SR.crawl_entry_url == url))
                .first()
            )
            if existing is None:
                raise
            existing.verification_state = STATE_VERIFIED
            existing.confidence = verdict.confidence
            self.session.flush()
            return
        self.metrics.sources_verified += 1
        logger.info("Registered verified source: {}", url)

    def _source_for_candidate(self, candidate: DiscoveryFrontier):
        """Find the SourceRegistry row for a SOURCE candidate (any state)."""
        from database.models.source_registry import SourceRegistry as SR

        return (
            self.session.query(SR)
            .filter(SR.official_url == candidate.url)
            .first()
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _expand_links(
        self,
        parent: DiscoveryFrontier,
        analyzed: AnalyzedCandidate,
        classification: ClassificationResult,
        run_id: UUID,
    ) -> int:
        """Push qualified outbound links back into the frontier."""
        if parent.depth >= self.config.bounds.max_depth:
            return 0
        added = 0
        parent_domain = domain_of(analyzed.final_url or analyzed.url)
        for link in analyzed.links:
            if added >= 15:  # per-page expansion budget
                break
            link_domain = domain_of(link.url)
            if not link_domain or link_domain == parent_domain and parent.depth >= self.config.bounds.max_depth - 1:
                continue
            anchor = (link.anchor_text or link.title or "").lower()
            relevant = any(
                t in anchor
                for t in self.config.terminology.get("scholarship", [])
                + self.config.terminology.get("provider", [])
            ) or parent.candidate_type == CandidateType.SOURCE
            if not relevant:
                continue
            observation = FrontierObservation(
                origin="link_expansion",
                source_url=analyzed.final_url or analyzed.url,
                anchor_text=link.anchor_text[:200] or None,
                run_id=str(run_id),
            )
            _, created = self.frontier.upsert_candidate(
                self.country.country_id,
                link.url,
                origin=CandidateOrigin.LINK_EXPANSION,
                candidate_type=parent.candidate_type,
                origin_url=parent.url,
                depth=parent.depth + 1,
                priority=4 if relevant else 6,
                observation=observation,
                run_id=run_id,
            )
            if created:
                added += 1
        return added

    def _record_classification(self, classification: ClassificationResult, candidate: DiscoveryFrontier) -> None:
        label = classification.label
        self.metrics.classification_labels[label] = self.metrics.classification_labels.get(label, 0) + 1
        if classification.routing in ("opportunity", "low_priority"):
            self.metrics.opportunities_retained += 1

    @staticmethod
    def _is_permanent_fetch_error(error: str) -> bool:
        return (
            error.startswith("http_4")
            or error == "robots_disallowed"
            or error.startswith("unsupported_content_type")
        )

    @staticmethod
    def _first_snippet(candidate: DiscoveryFrontier) -> str:
        for obs in (candidate.evidence or {}).get("observations", []):
            if obs.get("snippet"):
                return obs["snippet"]
        return ""

    def _scholarship_term_for(self) -> str:
        terms = self.config.terminology.get("scholarship", ["scholarship"])
        return terms[0] if terms else "scholarship"

    def _outcome(
        self,
        analyzed: AnalyzedCandidate,
        classification: ClassificationResult,
        extra: dict,
    ) -> dict:
        return {
            "classification": {
                "label": classification.label,
                "confidence": classification.confidence,
                "routing": classification.routing,
                "reasoning": classification.reasoning,
            },
            "page_signals": {
                "title": analyzed.title[:300],
                "final_url": analyzed.final_url,
                "links_found": len(analyzed.links),
                "text_length": len(analyzed.main_text),
            },
            **extra,
        }

    def _sample_provenance(self, candidate: DiscoveryFrontier, classification: ClassificationResult) -> None:
        if len(self.metrics.provenance_samples) >= 5:
            return
        observations = (candidate.evidence or {}).get("observations", [])
        if observations:
            self.metrics.provenance_samples.append(
                {
                    "url": candidate.url[:120],
                    "label": classification.label,
                    "observation": observations[0],
                }
            )

    def _record_run_degradation(self, run_id: UUID, error: str) -> None:
        """Record a fatal error on the metrics snapshot, rollback-safe.

        Called right after an exception escaped the loop, so the session may
        be poisoned (PendingRollback). Recover the transaction first —
        otherwise this handler crashes on its own SQL and masks the error
        that actually ended the run.
        """
        if not hasattr(self, "metrics_dict"):
            self.metrics_dict = {}
        self.metrics_dict["fatal_error"] = error[:500]
        try:
            self.session.rollback()
        except Exception:  # noqa: BLE001 — never let recovery mask the real error
            pass
