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
from database.models.exploration_run import ExplorationRun
from database.models.source_registry import SourceRegistry
from services.domain.source_trust import is_aggregator_host
from services.exploration.acquisition_service import AcquisitionService
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
from services.exploration.url_utils import domain_of, registered_domain
from services.exploration.verification_engine import (
    STATE_NEEDS_REVIEW,
    STATE_VERIFIED,
    VerificationEngine,
)

if TYPE_CHECKING:
    from database.models.provider import Provider


def org_identity_matches(provider_domain: str | None, url: str) -> bool:
    """True when a candidate URL belongs to the authority's provider domain.

    The authority resolver stores the *registered* domain (eTLD+1, e.g.
    ``uni.ac.jp``), while candidates arrive with full hosts (e.g.
    ``scholarships.uni.ac.jp``). Comparing the registered domain against
    the full host made the org-identity signal unreachable for every
    subdomain source — and with it the 0.75 auto-verify threshold, which
    cannot be reached without the +0.25 org-match signal. Compare
    registered domains on both sides.
    """
    if not provider_domain:
        return False
    host = domain_of(url)
    if not host:
        return False
    return registered_domain(host) == provider_domain


class ExplorationMetrics:
    """Aggregated run counters (reported honestly, never asserted)."""

    def __init__(self) -> None:
        self.queries_executed = 0
        self.discovery_queries = 0
        self.queries_failed = 0
        self.search_failure_categories: dict[str, int] = {}
        self.search_degraded_reason: str | None = None
        self.search_results = 0
        # Search results that point at a known third-party listing site. They
        # are never queued for country exploration: official-source-first, and
        # the aggregator service already exists for tracing an article back to
        # its provider.
        self.aggregator_candidates_skipped = 0
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
        # V0.1.3: the successful-extraction counter. AcquisitionService has
        # always produced it, but only the failure count was copied across, so
        # `exploration_run.metrics` carried no numerator for extraction and
        # every benchmark funnel printed "NOT MEASURABLE" for it. The two are
        # accumulated from the same call site so they cannot drift apart.
        self.extraction_succeeded = 0
        self.extraction_failures = 0
        self.acquisition_failures = 0
        self.duplicates_collapsed = 0
        self.link_expansions = 0
        self.retries = 0
        # V0.1.2: what the fetched pages actually were. Previously these lived
        # only on AcquisitionMetrics and were never copied into the run
        # snapshot, which is why "how many DETAIL vs UNKNOWN pages did we
        # fetch" had no answer in the database.
        self.page_intent_counts: dict[str, int] = {}
        self.pages_skipped_not_detail = 0
        self.pages_skipped_listing = 0
        self.listing_signals: dict[str, int] = {}
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
        # A source is acquired at most once per run. Several candidates can
        # resolve to one source (redirects, aliases), and re-fetching it would
        # repeat the same pages without producing anything new.
        self._acquired: set[UUID] = set()

    def _acquired_this_run(self, source) -> bool:
        return source.source_id in self._acquired

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
        # Published on the engine, not just captured locally, so the benchmark
        # harness can attribute run-scoped metrics by run_id: `start_run`
        # commits, so the row survives, but a caller holding only the engine had
        # no attribute to read.
        #
        # Deliberately NOT named `run`: `run` is this class's entry-point method,
        # and assigning an instance attribute of that name shadows it, so
        # `await engine.run()` would resolve to the ORM row and raise
        # "ExplorationRun object is not callable". Measured, not assumed --
        # test_exploration_loop.py::test_second_run_idempotent calls run()
        # twice on one engine and caught exactly that.
        self.current_run = run
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
        self.metrics.search_failure_categories = dict(self.search_provider.failure_categories)
        if self.metrics.search_failure_categories and not self.metrics.search_degraded_reason:
            self.metrics.search_degraded_reason = "one or more search queries failed"
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
        self.metrics.aggregator_candidates_skipped += self.frontier.skipped_aggregators

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

        # Rotation offset from how many runs this country has already had, not
        # from the wall clock. The clock made every run irreproducible: the same
        # country on the same day produced different queries, so a bad run could
        # not be re-run to confirm or refute it. This is stable, derived from
        # persisted state, and still rotates successive runs onto different
        # query combinations.
        prior_runs = (
            self.session.query(func.count())
            .filter(ExplorationRun.country_id == self.country.country_id)
            .scalar()
            or 0
        )
        plan = self.queries.generate_plan(run_offset=int(prior_runs))
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
        self.metrics.aggregator_candidates_skipped += outcome.skipped_aggregators
        if outcome.degraded_reason:
            self.metrics.search_degraded_reason = outcome.degraded_reason
            logger.warning("WebSearchSurface degraded: {}", outcome.degraded_reason)

        # Seed URLs from config (optional accelerator)
        for url in self.config.seed_urls:
            if is_aggregator_host(url):
                self.metrics.aggregator_candidates_skipped += 1
                continue
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
                func.lower(SourceRegistry.status).in_(["active", "provisional"]),
            )
            .limit(20)
            .all()
        )
        for source in known:
            entry_url = source.crawl_entry_url or source.official_url
            if is_aggregator_host(entry_url):
                self.metrics.aggregator_candidates_skipped += 1
                continue
            _, created = self.frontier.upsert_candidate(
                self.country.country_id,
                entry_url,
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

            # Read the identity off the candidate *before* the try block, and
            # hold only immutable primitives.
            #
            # Processing can itself roll the session back — ProviderResolver
            # does exactly that to recover from a provider UniqueViolation
            # (provider_resolver.py). A rollback expires every loaded
            # attribute of the candidate, so the instance in hand may be
            # unusable by the time we get back here: reading `candidate.url`
            # raises ObjectDeletedError. The earlier fix captured the URL as a
            # string, which removed one touch but left the handler still
            # handing the dead instance to mark_failed_transient. The handler
            # then crashed while handling the crash and `run()` recorded the
            # run as failed — 7 of 7 live runs died this way.
            #
            # So the handler is keyed on candidate_id alone and re-reads the
            # row by primary key. A candidate whose row the rollback discarded
            # is simply absent, which is an ordinary outcome.
            candidate_url = candidate.url
            candidate_id = candidate.candidate_id

            try:
                await self._process_candidate(candidate, run_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Candidate {} processing error: {}", candidate_url, exc)
                # A failed flush poisons the session; recover the transaction
                # before any further SQL (mark_failed_by_id included).
                self.session.rollback()
                retried = self.frontier.mark_failed_by_id(
                    candidate_id, str(exc), self.config.bounds.max_retries
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
            self.frontier.mark_rejected(
                candidate,
                self._outcome(analyzed, classification, {"reason": "employment page"}),
            )
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
                org_identity_match=bool(provider) and org_identity_matches(
                    resolution_outcome.get("authority", {}).get("provider_domain"),
                    analyzed.final_url or analyzed.url,
                ),
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
            elif verdict.state == STATE_NEEDS_REVIEW:
                # Persisted rather than counted. The queue is only truthful if
                # a source that verification could not settle is actually in it.
                self._register_needs_review(candidate, analyzed, provider, verdict, run_id)

        # ---- 13-14. SCHOLARSHIP ACQUISITION from verified sources ----
        # Any verified source is a candidate for acquisition, not only
        # SOURCE-type candidates. M8 acquired 54 sources and left the 51
        # verified sources born from opportunity/provider candidates entirely
        # unused, because the gate below only looked at candidate_type.
        #
        # What stops this becoming "crawl everything" is the policy inside
        # AcquisitionService: a source page is expanded for scholarship-bearing
        # links and only those are fetched. Each source is acquired at most
        # once per run, and acquisition state is recorded per source.
        source = self._source_for_candidate(candidate)
        if source is not None and source.is_verified() and not self._acquired_this_run(source):
            acq = await self.acquisition.acquire_from_source(source)
            self._acquired.add(source.source_id)
            self.metrics.scholarships_persisted += acq.scholarships_persisted
            self.metrics.extraction_succeeded += acq.extraction_succeeded
            self.metrics.extraction_failures += acq.extraction_failed
            self.metrics.duplicates_collapsed += acq.duplicates_collapsed
            if acq.errors:
                # Failures are counted, not hidden behind a zero count.
                self.metrics.acquisition_failures += len(acq.errors)
            resolution_outcome["acquisition"] = {
                "page_type": source.page_type,
                "urls": acq.scholarship_urls_found,
                "fetched": acq.pages_fetched,
                "persisted": acq.scholarships_persisted,
                "errors": acq.errors[:5],
                "state": source.acquisition_state,
                # Which pages were fetched and what each one was judged. The
                # frontier audit named this as unmeasurable: these counters
                # existed on AcquisitionMetrics and were dropped on the floor
                # at the call site, so the DETAIL/UNKNOWN/INDEX split for every
                # fetched page was unrecoverable after a run finished. They are
                # per-source and aggregate here.
                "page_intent_counts": dict(acq.page_intent_counts),
                "skipped_not_detail": acq.pages_skipped_not_detail,
                "skipped_listing": acq.pages_skipped_listing,
            }
            for verdict_name, count in acq.page_intent_counts.items():
                self.metrics.page_intent_counts[verdict_name] = (
                    self.metrics.page_intent_counts.get(verdict_name, 0) + count
                )
            self.metrics.pages_skipped_not_detail += acq.pages_skipped_not_detail
            self.metrics.pages_skipped_listing += acq.pages_skipped_listing
            for signal_name, count in acq.listing_signals.items():
                self.metrics.listing_signals[signal_name] = (
                    self.metrics.listing_signals.get(signal_name, 0) + count
                )

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

        Identity is the URL *hash*, not the URL string. Before M9 the stored
        value was the redirected final URL while lookups used the raw frontier
        URL, so one redirect could register a source and then fail to find it
        again. `resolve_url_identity` gives one canonical value and one hash;
        `find_source` looks up by hash, falling back to the raw columns so
        rows written before the column existed stay reachable.

        Idempotent: re-running exploration over the same site updates the
        existing row rather than inserting a duplicate.
        """
        from database.models.source_registry import SourceRegistry as SR
        from services.exploration.acquisition_policy import (
            AcquisitionState,
            classify_page,
            find_source,
            resolve_url_identity,
        )

        url = analyzed.final_url or analyzed.url

        # A blocked host is blocked here too. The frontier refuses aggregators
        # and social platforms at admission, but this path is reached from
        # candidates that were already admitted, and a site like wentchina.com
        # (a study-in-China blog) was landing in the registry as an Active
        # source with the same standing as a university. Review is where a
        # human sees records, not where a rule the project already decided is
        # quietly bypassed.
        from services.domain.source_trust import is_blocked_source_host

        if is_blocked_source_host(url):
            logger.info("{}: not registering blocked source {}", type(self).__name__, url[:120])
            return

        canonical, digest = resolve_url_identity(url)
        assessment = classify_page(url, title=analyzed.title or "")

        existing = find_source(self.session, url)
        if existing is not None:
            self._apply_verification(existing, verdict)
            # A redirect must not silently disable acquisition: the reachable
            # URL stays as the crawl entry, and the canonical form is recorded
            # so the identity is stable from now on.
            if analyzed.final_url and not existing.official_url:
                existing.official_url = analyzed.final_url[:2048]
            if canonical and not existing.canonical_url:
                existing.canonical_url = canonical
                existing.url_hash = digest
            if assessment.page_type and not existing.page_type:
                existing.page_type = assessment.page_type
            self.session.flush()
            return

        source = SR(
            source_name=(analyzed.title or url)[:255],
            country_id=self.country.country_id,
            provider_id=provider.provider_id if provider else None,
            official_url=url[:2048],
            crawl_entry_url=url[:2048],
            canonical_url=canonical[:2048] if canonical else None,
            url_hash=digest or None,
            page_type=assessment.page_type,
            crawl_method="Playwright",
            connector_name="generic_playwright",
            crawl_frequency="monthly",
            priority=3,
            robots_allowed=True,
            requires_login=False,
            status="Active",
            verification_state=STATE_VERIFIED,
            confidence=verdict.confidence,
            acquisition_state=AcquisitionState.PENDING,
            discovered_via={
                "frontier_candidate": str(candidate.candidate_id),
                "origin": candidate.origin,
                "origin_query": candidate.origin_query,
                "run_id": str(run_id),
                "signals": verdict.signals,
                "page_type": assessment.page_type,
                "page_type_reasons": assessment.reasons,
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
            existing = find_source(self.session, url)
            if existing is None:
                raise
            self._apply_verification(existing, verdict)
            self.session.flush()
            return
        self.metrics.sources_verified += 1
        logger.info("Registered verified source: {} [{}]", url, assessment.page_type)

    def _register_needs_review(
        self,
        candidate: DiscoveryFrontier,
        analyzed: AnalyzedCandidate,
        provider: "Provider | None",
        verdict,
        run_id: UUID,
    ) -> None:
        """Persist a source verification could not settle.

        M8 initialised `sources_needs_review` and printed it, but nothing ever
        incremented it, so the queue was always empty and the metric was a
        lie by omission. A source whose verification is genuinely undecided is
        now a real row in NEEDS_REVIEW, which is also what acquisition_state
        and page_type get recorded on.
        """
        from database.models.source_registry import SourceRegistry as SR
        from services.exploration.acquisition_policy import (
            classify_page,
            find_source,
            resolve_url_identity,
        )

        url = analyzed.final_url or analyzed.url
        canonical, digest = resolve_url_identity(url)
        assessment = classify_page(url, title=analyzed.title or "")

        existing = find_source(self.session, url)
        if existing is not None:
            if (
                existing.verification_state != STATE_NEEDS_REVIEW
                and existing.can_transition_to(STATE_NEEDS_REVIEW)
            ):
                existing.verification_state = STATE_NEEDS_REVIEW
                # Counted on the transition, not on the verdict, so re-running
                # exploration over the same site does not inflate the metric.
                self.metrics.sources_needs_review += 1
            existing.confidence = verdict.confidence
            if assessment.page_type and not existing.page_type:
                existing.page_type = assessment.page_type
            self.session.flush()
            return

        source = SR(
            source_name=(analyzed.title or url)[:255],
            country_id=self.country.country_id,
            provider_id=provider.provider_id if provider else None,
            official_url=url[:2048],
            crawl_entry_url=url[:2048],
            canonical_url=canonical[:2048] if canonical else None,
            url_hash=digest or None,
            page_type=assessment.page_type,
            crawl_method="Playwright",
            connector_name="generic_playwright",
            crawl_frequency="monthly",
            priority=5,
            robots_allowed=True,
            requires_login=False,
            status="Active",
            verification_state=STATE_NEEDS_REVIEW,
            confidence=verdict.confidence,
            discovered_via={
                "frontier_candidate": str(candidate.candidate_id),
                "origin": candidate.origin,
                "origin_query": candidate.origin_query,
                "run_id": str(run_id),
                "signals": verdict.signals,
                "page_type": assessment.page_type,
                "verification": "needs_review",
            },
        )
        self.session.add(source)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            return
        self.metrics.sources_needs_review += 1
        logger.info("Registered source needing review: {}", url)

    def _apply_verification(self, source, verdict) -> None:
        """Move a source to VERIFIED, counting the transition only once.

        The legality check is the model's, so an illegal move (a REJECTED
        source resurrecting itself) is refused rather than silently applied.
        Counting only real transitions is what keeps `sources_verified` equal
        to the number of verified sources in the database.
        """
        already_verified = source.verification_state == STATE_VERIFIED
        if not already_verified:
            if not source.can_transition_to(STATE_VERIFIED):
                logger.warning(
                    "Refusing illegal verification transition {} -> {} for source {}",
                    source.verification_state, STATE_VERIFIED, source.source_id,
                )
                return
            source.verification_state = STATE_VERIFIED
            if not already_verified:
                self.metrics.sources_verified += 1
        source.confidence = verdict.confidence

    def _source_for_candidate(self, candidate: DiscoveryFrontier):
        """Find the SourceRegistry row for a candidate, any state.

        By URL hash rather than raw string, so a candidate whose URL
        redirected during registration still resolves to its source.
        """
        from services.exploration.acquisition_policy import find_source

        return find_source(self.session, candidate.url)

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
