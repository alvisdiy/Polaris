"""AcquisitionService — frontier-aware scholarship acquisition.

Reuses the existing pipeline untouched:
  fetch → RawDocument → cleaner → extractor (DeterministicLLMClient) →
  validator → Scholarship persistence

Adds: scholarship identity dedup (one canonical Scholarship per
provider+name+country, regardless of how many sites published it),
provenance recording, and acquisition policy (a verified source is a place to
look, not a scholarship, so only pages that look like one programme are
extracted).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import func

from services.domain.source_trust import aggregator_host
from services.exploration.candidate_analyzer import CandidateAnalyzer
from services.scholarship.freshness import classify_deadline

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from database.models.source_registry import SourceRegistry


def scholarship_identity_key(provider_id, name: str, country_id) -> str:
    """Canonical identity for one scholarship.

    Delegates to :mod:`services.scholarship.identity`, which every creation
    path shares. This function previously lowercased and collapsed
    whitespace inline, which produced a *different* key from the repository's
    — so a record created here and a record created by the ingestion
    orchestrator could both claim the same scholarship. One definition, one
    key.
    """
    from services.scholarship.identity import scholarship_identity_key as canonical_key

    return canonical_key(provider_id, name, country_id)


def _utcnow():
    return datetime.now(timezone.utc)


#: How many of a source's own section pages may be expanded when a run would
#: otherwise yield nothing. Three is enough for the shapes seen on real sources
#: (hub → section → listing) and keeps the worst case bounded: a source that
#: yields nothing costs at most this many extra navigations plus the entry page.
MAX_SECTION_EXPANSIONS = 3

#: How many overview/index pages inside one source may be expanded into their
#: programme children, and how many children each may contribute. A ministry's
#: "types of scholarships" page is an index; the programmes live one level
#: below it. Without this the run fetched the index, correctly refused to
#: extract it, and never read the pages it linked to.
MAX_OVERVIEW_EXPANSIONS = 2
MAX_CHILD_PAGES_PER_OVERVIEW = 4


@dataclass
class AcquisitionMetrics:
    scholarship_urls_found: int = 0
    pages_fetched: int = 0
    extraction_succeeded: int = 0
    extraction_failed: int = 0
    scholarships_persisted: int = 0
    duplicates_collapsed: int = 0
    # V0.1: what the fetched page actually was. `pages_skipped_not_detail`
    # is the number this wiring exists to reduce — POST-M10 spent most of its
    # budget extracting index pages that could never be one scholarship.
    page_intent_counts: dict = field(default_factory=dict)
    pages_skipped_not_detail: int = 0
    # V0.1.1: pages that passed page intent but are a listing or a non-
    # opportunity page. Separate from `pages_skipped_not_detail` because the
    # two are different decisions: that counter is "this page is not one
    # scholarship, follow it instead"; this one is "extracting this page would
    # have produced a record that is not a scholarship at all".
    pages_skipped_listing: int = 0
    listing_signals: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    # M12 bounded-run observability: what the ranked list contained before and
    # after the entry-page + same-page dedup, so a single-source run is externally
    # auditable beyond the aggregate counters.
    discovered_ranked_before_dedup: list[dict] = field(default_factory=list)
    scholarship_page_urls_after_dedup: list[dict] = field(default_factory=list)

    # Stage-level counts. `scholarship_urls_found` alone could not distinguish
    # "the page describes nothing" from "three links were portals and one was
    # guidance", which is the difference between a broken source and a broken
    # rule. Every discovered link is counted by the verdict it received, and
    # every rejected link by the reason.
    links_extracted: int = 0
    candidates_by_page_type: dict = field(default_factory=dict)
    rejection_reasons: dict = field(default_factory=dict)
    # Zero-yield recovery: whether the source's own entry page was tried as one
    # opportunity, and which of its section pages were expanded a level deeper.
    entry_page_processed: bool = False
    expanded_section_urls: list[str] = field(default_factory=list)
    links_from_expansion: int = 0


class AcquisitionService:
    """Feeds verified sources into the existing extraction pipeline.

    The pipeline is unchanged; what changed is what gets fed into it. A
    verified source is a *place to look*, not a scholarship, so this service
    classifies the page first and extracts only pages that actually look like
    one programme (see `acquisition_policy`).
    """

    def __init__(
        self,
        session: "Session",
        analyzer: CandidateAnalyzer | None = None,
        origin: str = "exploration",
    ) -> None:
        self.session = session
        self.analyzer = analyzer or CandidateAnalyzer()
        # How records this service creates entered the knowledge base. Stamped
        # on every row so metrics can tell exploration output from seeds.
        self.origin = origin

    async def acquire_from_source(
        self,
        source: "SourceRegistry",
        max_pages: int = 10,
        *,
        follow_indexes: bool = True,
        max_index_depth: int = 1,
        max_index_expansions: int = MAX_OVERVIEW_EXPANSIONS,
        max_children_per_index: int = MAX_CHILD_PAGES_PER_OVERVIEW,
    ) -> AcquisitionMetrics:
        """Discover scholarship URLs on a verified source and run the pipeline.

        Acquisition outcome is recorded on the source row. M9 forbids silent
        failure: a source that could not be fetched, or that yielded no
        scholarship pages, is distinguishable in the database from one that
        was never tried.
        """
        from services.exploration.acquisition_policy import (
            AcquisitionState,
            PageType,
            assess_candidate_links,
            rank_candidate_urls,
            resolve_url_identity,
        )
        from services.exploration.url_utils import domain_of, normalize_url

        metrics = AcquisitionMetrics()

        from services.ingestion.connectors.base_connector import ConnectorConfig
        from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector
        from services.ingestion.real_extractor import DeterministicLLMClient
        from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
        from services.ingestion.repositories.raw_document_repository import RawDocumentRepository

        entry_url = source.crawl_entry_url or source.official_url
        canonical, digest = resolve_url_identity(entry_url)
        if canonical and digest and not source.url_hash:
            source.canonical_url = canonical
            source.url_hash = digest

        # A third-party listing site is a discovery lead, not an official
        # source. Fetching it would only produce a record whose official page
        # is the aggregator, which the review gate now refuses anyway; stop
        # before spending the fetch and record why.
        aggregator = aggregator_host(entry_url)
        if aggregator:
            source.acquisition_state = AcquisitionState.SKIPPED
            source.acquisition_error = (
                f"third-party aggregator ({aggregator}); resolve the official page first"
            )[:2000]
            metrics.errors.append(source.acquisition_error)
            self.session.flush()
            return metrics

        config = ConnectorConfig(
            source_id=source.source_id,
            url=entry_url,
            timeout=30,
            user_agent="PolarisBot/0.2 (+discovery research)",
        )
        connector = GenericPlaywrightConnector(config)
        llm_client = DeterministicLLMClient()
        raw_repo = RawDocumentRepository(self.session)
        mapper = RawDocumentMapper()

        source.acquisition_attempts = (source.acquisition_attempts or 0) + 1
        source.last_acquisition_at = _utcnow()

        try:
            await connector.connect()
            # Discover scholarships on the source page. Today the connector
            # returns candidate URLs only, but the wiring below already accepts
            # anchor text when a connector provides it, so a future discovery
            # improvement can flow straight into ranking without another policy
            # change.
            # Anchor text travels with the URL when the connector can supply it.
            # A query-based detail link (``view.do?seq=759978``) says nothing
            # about funding on its own; the label next to it does. Dropping the
            # label here is what left the ranked set empty on the MOFA entry
            # page. Connectors that only implement ``discover`` still work: they
            # contribute an empty anchor and are ranked on their URL alone.
            discover_with_context = getattr(connector, "discover_with_context", None)
            if callable(discover_with_context):
                candidates = await discover_with_context()
            else:
                candidates = [(url, "") for url in await connector.discover()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Acquisition discovery failed for {}: {}", source.source_id, exc)
            metrics.errors.append(f"discover: {exc}")
            # Recorded, not swallowed: the next run can see this source failed
            # and why, instead of treating it as merely untried.
            source.acquisition_state = AcquisitionState.FAILED
            source.acquisition_error = f"discover: {exc}"[:2000]
            self.session.flush()
            await connector.close()
            return metrics

        candidate_urls = [url for url, _anchor in candidates]
        metrics.scholarship_urls_found = len(candidate_urls)
        metrics.links_extracted = len(candidate_urls)

        country_domain = domain_of(entry_url)
        assessments = assess_candidate_links(candidates, country_domain=country_domain)
        for assessment in assessments:
            metrics.candidates_by_page_type[assessment.page_type] = (
                metrics.candidates_by_page_type.get(assessment.page_type, 0) + 1
            )
            if assessment.is_scholarship_page:
                continue
            reason = assessment.reasons[0] if assessment.reasons else "no reason recorded"
            key = f"{assessment.page_type}: {reason}"[:200]
            metrics.rejection_reasons[key] = metrics.rejection_reasons.get(key, 0) + 1

        ranked = rank_candidate_urls(
            candidates,
            limit=max_pages,
            country_domain=country_domain,
            assessments=assessments,
        )

        # It is useful in the bounded live run to see which ranked URLs were
        # actually considered, including the ones later dropped by the entry-page
        # dedup and the same-page dedup. The recorded list is the canonical-deduped
        # set the acquisition loop will actually fetch.
        metrics.discovered_ranked_before_dedup = [
            {"url": p.url, "canonical_url": p.canonical_url, "score": p.score}
            for p in ranked
        ]

        # Only the ranked links are queued here. The source's own entry page is
        # not fetched *because it was discovered*: it is the index the ranked
        # links were read from, and that boundary is pinned by
        # ``tests/integration/test_entry_page_not_acquired``.
        #
        # It is fetched later, and only when the ranked set came back empty, as
        # one opportunity in its own right — a verified source whose entry URL
        # *is* one programme's page (the MOFA Korea announcements) was otherwise
        # acquired for its outbound links alone and ended at zero with nothing
        # persisted. See `_recover_zero_yield`.
        #
        # What this does enforce is that a connector handing back its own URL as
        # a discovered link does not make the same page fetch twice. Normalize
        # the entrypoint once so both sides are compared on the same canonical
        # basis.
        normalized_entry_canonical = normalize_url(entry_url)
        if not normalized_entry_canonical:
            normalized_entry_canonical = entry_url
        # Drop any ranked link whose canonical form is the same page as the
        # source's own entry URL. A connector that returns its own URL as a
        # discovered link would otherwise waste an intent-classified fetch, and
        # a portal would look like it returned a page when it only returned
        # itself.
        page_urls: list[str] = []
        for p in ranked:
            raw = p.canonical_url or p.url
            p_canonical = normalize_url(raw) or raw
            if p_canonical == normalized_entry_canonical:
                continue
            page_urls.append(p.url)
        # Record what was found, including pages later rejected, so a reviewer
        # can see the policy's decision rather than an absence. The recorded list
        # is the same canonical-deduped set the acquisition loop will fetch.
        recorded: list[dict] = []
        for p in ranked:
            raw = p.canonical_url or p.url
            p_canonical = normalize_url(raw) or raw
            if p_canonical == normalized_entry_canonical:
                continue
            recorded.append(
                {"url": p.url, "canonical_url": p.canonical_url, "score": p.score, "reasons": p.reasons}
            )
        entry_error: str | None = None
        # A source may already know its scholarship pages: a site-specific
        # importer enumerates an official database and stores the detail URLs
        # on the source. Those pages are the work list; discovery still runs
        # for pages the importer did not know about.
        seeded_urls: list[str] = []
        for item in source.scholarship_page_urls or []:
            value = item.get("url") if isinstance(item, dict) else item
            if isinstance(value, str) and value.strip():
                seeded_urls.append(value.strip())
        existing_canonical = {normalize_url(url) or url for url in page_urls}
        seeded_admitted: list[str] = []
        for seeded in seeded_urls:
            seeded_canonical = normalize_url(seeded) or seeded
            if seeded_canonical == normalized_entry_canonical:
                continue
            if seeded_canonical in existing_canonical:
                continue
            seeded_admitted.append(seeded)
            existing_canonical.add(seeded_canonical)
        # The importer's work list goes first. It is an enumeration of an
        # official database, so it is the highest-precision set available; a
        # portal's discovered links are guesses by comparison. Appending it
        # would let discovered links consume a page budget before a single
        # known programme was fetched.
        page_urls = seeded_admitted + page_urls
        if not page_urls:
            # Nothing ranked. Before calling this source empty, look where the
            # pipeline has not looked yet: the entry page as one opportunity,
            # then one level deeper through the entry page's own section pages.
            # Both are bounded, both run only on this path, so a source that
            # already yields pages is unaffected.
            recovered = await self._recover_zero_yield(
                source,
                connector,
                entry_url,
                assessments,
                metrics,
                llm_client,
                raw_repo,
                mapper,
                max_pages=max_pages,
                country_domain=country_domain,
            )
            page_urls = [p.url for p in recovered]
            for candidate in recovered:
                recorded.append(
                    {
                        "url": candidate.url,
                        "canonical_url": candidate.canonical_url,
                        "score": candidate.score,
                        "reasons": candidate.reasons,
                    }
                )

        source.scholarship_page_urls = (
            [{"url": url, "origin": "source_seed"} for url in seeded_urls]
            + recorded
        )[:1000]
        metrics.scholarship_page_urls_after_dedup = recorded
        # A ranked page can turn out to be an overview or an index. That is a
        # correct verdict for the page, but not the end of the source: the
        # programmes it links to are one level below it. Expand a bounded
        # number of those children, with details (depth 0) processed first so
        # an index cannot crowd real programmes out of the page budget.
        pending: list[tuple[str, int]] = [(url, 0) for url in page_urls]
        # Exhaustive mode starts at the provider's own entry page: a homepage
        # is not a scholarship, but it is where the "Scholarships" section is
        # linked from. Without this, a provider whose homepage has no
        # detail-shaped link is reported empty while its scholarship index sits
        # one click away.
        if max_index_depth > 1 and normalized_entry_canonical not in {
            normalize_url(url) or url for url, _ in pending
        }:
            pending.append((entry_url, 0))
        processed: set[str] = set()
        overview_expansions = 0
        while pending and metrics.pages_fetched < max_pages:
            url, depth = pending.pop(0)
            if url in processed:
                continue
            processed.add(url)

            try:
                children = await self._process_page(
                    source, connector, url, metrics, llm_client, raw_repo, mapper
                )
            except Exception as exc:  # noqa: BLE001
                metrics.errors.append(f"{url}: {exc}"[:300])
                logger.debug("Acquisition failed for {}: {}", url, exc)
                if url == entry_url:
                    # The source's own URL failing to fetch is a different
                    # fact from a discovered link failing: it means the
                    # source itself could not be read at all.
                    entry_error = str(exc)[:300]
                continue

            if (
                children
                and follow_indexes
                and depth < max_index_depth
                and overview_expansions < max_index_expansions
            ):
                overview_expansions += 1
                logger.info(
                    "Expanding {} programme link(s) from overview {}",
                    len(children), url,
                )
                for child in children[:max_children_per_index]:
                    if child not in processed:
                        pending.append((child, depth + 1))

        try:
            await connector.close()
        except Exception:  # noqa: BLE001
            pass

        if metrics.extraction_failed and not metrics.extraction_succeeded:
            # Every page we tried failed to yield a valid record. That is a
            # pipeline problem, and recording it as success would hide it.
            source.acquisition_state = AcquisitionState.FAILED
            source.acquisition_error = (
                f"{metrics.extraction_failed} page(s) fetched, none extracted"
            )[:2000]
        elif metrics.extraction_succeeded == 0 and not metrics.scholarship_page_urls_after_dedup:
            if entry_error:
                source.acquisition_state = AcquisitionState.FAILED
                source.acquisition_error = f"entry page fetch failed: {entry_error}"[:2000]
            else:
                source.page_type = source.page_type or PageType.SOURCE_PAGE
                source.acquisition_state = AcquisitionState.NO_SCHOLARSHIP_PAGES
                # The message has to say *where* the run looked, not only that
                # it found nothing: "0 links" and "40 links, none of them a
                # scholarship page, two sections expanded" are different
                # diagnoses and used to read the same in the database.
                source.acquisition_error = (
                    f"{len(candidate_urls)} links found, none classified as a scholarship page; "
                    f"entry page processed as one opportunity: {metrics.entry_page_processed}; "
                    f"sections expanded: {len(metrics.expanded_section_urls)} "
                    f"({metrics.links_from_expansion} further links); "
                    f"{metrics.pages_skipped_not_detail} page(s) skipped as not one scholarship, "
                    f"{metrics.pages_skipped_listing} as a listing; "
                    f"{metrics.pages_fetched} page(s) fetched"
                )[:2000]
                logger.info(
                    "Source {} yielded no scholarship pages ({} links; entry page processed: {}; "
                    "{} section(s) expanded; {} pages fetched)",
                    source.source_id, len(candidate_urls), metrics.entry_page_processed,
                    len(metrics.expanded_section_urls), metrics.pages_fetched,
                )
        else:
            source.acquisition_state = AcquisitionState.ACQUIRED
            source.acquisition_error = None
        self.session.flush()

        return metrics

    async def _process_page(
        self,
        source: "SourceRegistry",
        connector,
        url: str,
        metrics: AcquisitionMetrics,
        llm_client,
        raw_repo,
        mapper,
    ) -> list[str]:
        """Fetch one page and run it through intent → listing guard → extraction.

        Shared by the source's own entry page and every ranked link, so both
        faces the same boundaries: page intent decides what kind of page it
        is, the listing guard stops known aggregators, and only then does the
        existing pipeline extract and persist.

        Returns programme links when the page is an overview or an index: the
        caller may expand them one level deeper. A detail page returns an
        empty list.
        """
        from services.exploration.listing_guard import ListingGuard, classify_listing_page
        from services.exploration.page_intent import PageIntent
        from services.ingestion.orchestrator import run_pipeline

        fetch_result = await connector.fetch(url)
        metrics.pages_fetched += 1
        raw_doc = mapper.to_orm(fetch_result)

        existing = raw_repo.get_by_source_and_checksum(raw_doc.source_id, raw_doc.checksum)
        if existing:
            raw_doc = existing
        else:
            raw_doc = raw_repo.save(raw_doc)

        verdict, signals, cleaned = self._page_intent(raw_doc)
        metrics.page_intent_counts[verdict.intent] = (
            metrics.page_intent_counts.get(verdict.intent, 0) + 1
        )
        # Phase 9: the frontier column for this existed from the start
        # and nothing wrote to it. Recording the signals here is what
        # makes a rejected page explainable afterwards — the verdict
        # and the evidence for it sit on the same row.
        self._record_signals(source, url, signals)
        if verdict.intent != PageIntent.SCHOLARSHIP_DETAIL and verdict.intent != PageIntent.UNKNOWN:
            # The URL policy already had a say; this is the page's own
            # evidence saying no. An index or overview page cannot
            # yield one scholarship, and extracting it is how "Fees
            # and funding" reaches the knowledge base.
            #
            # UNKNOWN is deliberately extracted. It means the classifier
            # did not find enough evidence either way, not that the page
            # is known to be a list — and discarding those would throw
            # away real opportunities on a signal that is silent rather
            # than negative. Anything it yields still lands in review.
            metrics.pages_skipped_not_detail += 1
            logger.info(
                "Skipping extraction of {}: page intent {} ({}). Evidence: {}",
                url, verdict.intent, verdict.confidence,
                "; ".join(verdict.evidence[:3]),
            )
            if verdict.intent in (
                PageIntent.SCHOLARSHIP_OVERVIEW, PageIntent.SCHOLARSHIP_INDEX
            ):
                return self._programme_links(cleaned, url)
            if verdict.intent in (
                PageIntent.PROVIDER_INFORMATION,
                PageIntent.UNIVERSITY_INFORMATION,
                PageIntent.GENERAL_PROGRAMME_PAGE,
            ):
                # A provider homepage is where the scholarship index is linked
                # from. Follow those section links; the index then yields the
                # programme pages.
                return self._scholarship_section_links(cleaned, url)
            return []

        # The listing guard runs here, after page intent and before
        # extraction, so a listing page never reaches
        # run_pipeline(). In V0.1 an aggregator category page passed
        # page intent (it carries deadline and eligibility
        # boilerplate) and produced a scholarship named after the
        # listing; a marketing page passed as UNKNOWN and produced one
        # named after its largest metric. Neither is catchable by the
        # quality gate, which checks a record's fields rather than
        # whether the page described one opportunity.
        guard = classify_listing_page(
            page_title=cleaned.page_title,
            headings=cleaned.headings,
            anchors=cleaned.anchors,
            text=cleaned.clean_text,
            intent=verdict,
        )
        if not guard.should_extract:
            metrics.pages_skipped_listing += 1
            for name in guard.signals:
                metrics.listing_signals[name] = (
                    metrics.listing_signals.get(name, 0) + 1
                )
            # The frontier row has to be able to explain this skip
            # later. Recording only the intent signals would leave a
            # candidate whose page_signals say SCHOLARSHIP_DETAIL
            # while the pipeline silently dropped it — the page would
            # look untouched and could be retried forever.
            self._record_signals(
                source,
                url,
                {
                    **signals,
                    "listing_guard": {
                        "reason": ListingGuard.REASON,
                        "verdict": guard.verdict,
                        "signals": list(guard.signals),
                    },
                },
            )
            logger.info(
                "Skipping extraction of {}: {} ({})",
                url, ListingGuard.REASON, ", ".join(guard.signals),
            )
            return self._programme_links(cleaned, url)

        result = run_pipeline(str(raw_doc.document_id), self.session, llm_client)
        if not result.is_valid or result.raw_extraction.scholarship is None:
            metrics.extraction_failed += 1
            return []

        metrics.extraction_succeeded += 1
        persisted = self._persist_with_dedup(result, str(raw_doc.document_id))
        if persisted:
            metrics.scholarships_persisted += 1
        else:
            metrics.duplicates_collapsed += 1
        return []

    def _scholarship_section_links(self, cleaned, page_url: str, *, limit: int = 5) -> list[str]:
        """Links from a provider page to its scholarship/funding sections.

        A homepage anchor is usually a bare noun — "Scholarships", "Financial
        Aid", "Funding" — so the programme-link rule (which requires a
        substantive name) correctly refuses it. Here the bare noun is the
        signal: this is the section to follow, not a record to create.
        """
        from services.domain.source_trust import is_blocked_source_host
        from services.exploration.page_intent import FUNDING_TERMS
        from services.exploration.url_utils import domain_of

        domain = domain_of(page_url)
        children: list[str] = []
        seen: set[str] = set()

        for link in cleaned.anchor_links:
            href = (link.href or "").strip()
            anchor = (link.text or "").strip()
            if not href or not anchor or href == page_url or href in seen:
                continue
            if domain_of(href) != domain:
                continue
            if is_blocked_source_host(href):
                continue
            lowered = anchor.casefold()
            if not any(term in lowered for term in FUNDING_TERMS):
                continue
            seen.add(href)
            children.append(href)
            if len(children) >= limit:
                break
        return children

    def _programme_links(self, cleaned, page_url: str, *, limit: int = MAX_CHILD_PAGES_PER_OVERVIEW) -> list[str]:
        """Programme links on an overview/index page, in page order.

        The URL policy alone is not enough here. Real official programme pages
        look like ``/mext-scholarships/`` or ``/jasso/`` — no year, no singular
        programme head — so the classifier correctly refuses to call them a
        detail page from the URL, and an expansion driven by that verdict
        returned nothing. On an overview page the *anchor* is the evidence:
        "Japanese Government (MEXT) Scholarship" names a programme even when
        the slug does not.

        A child must therefore:

        * be on the same registered domain as the overview;
        * have an anchor that names something beyond a bare funding noun
          (``Scholarships`` is a section, ``MEXT Scholarship`` is a programme);
        * not be a section label, guidance page, or blocked host.
        """
        from services.domain.page_labels import section_label
        from services.domain.source_trust import is_blocked_source_host
        from services.exploration.page_intent import FUNDING_TERMS
        from services.exploration.url_utils import domain_of
        from services.ingestion.extraction_quality import substantive_words

        domain = domain_of(page_url)
        children: list[str] = []
        seen: set[str] = set()

        for link in cleaned.anchor_links:
            href = (link.href or "").strip()
            anchor = (link.text or "").strip()
            if not href or not anchor or href == page_url or href in seen:
                continue
            if domain_of(href) != domain:
                continue
            if is_blocked_source_host(href):
                continue
            if section_label(anchor):
                continue
            lowered = anchor.casefold()
            if not any(term in lowered for term in FUNDING_TERMS):
                continue
            if not substantive_words(anchor):
                continue

            seen.add(href)
            children.append(href)
            if len(children) >= limit:
                break
        return children

    async def _recover_zero_yield(
        self,
        source: "SourceRegistry",
        connector,
        entry_url: str,
        assessments,
        metrics: AcquisitionMetrics,
        llm_client,
        raw_repo,
        mapper,
        *,
        max_pages: int,
        country_domain: str | None,
    ) -> list:
        """What to try when the ranked set is empty, in order of cost.

        Two failures of the 2026-10 live run ended here, and both are failures
        of *where* the pipeline looked rather than of what it concluded:

        1. MOFA Korea publishes each scholarship announcement as one board
           record (``view.do?seq=759978``). The source's entry URL *is* that
           announcement, so discovery could only ever find its outbound links,
           and a page that is one programme was never read as one. It is read
           now — first, because it costs one fetch — and only when the source's
           own name and URL say it is a programme page. The page's own content
           still decides: page intent and the listing guard run unchanged.

        2. The University of Tsukuba's entry page is a category page whose
           rows are links to its own section pages; the programme records live
           one level below, on a listing that renders 1,415 of them. Discovery
           stopped at level one, so none of them were ever reachable.

        Both steps are bounded and run only when the ranked set is empty, so a
        source that already yields pages is untouched.

        Returns the candidates the caller should still acquire, each carrying
        its own score and reasons, so a recovered page is as explainable in the
        source row as a ranked one.
        """
        from services.exploration.acquisition_policy import (
            PageType,
            classify_page,
            rank_candidate_urls,
        )
        from services.exploration.url_utils import normalize_url

        entry_canonical = normalize_url(entry_url) or entry_url

        entry_assessment = classify_page(entry_url, title=source.source_name or "")
        if entry_assessment.is_scholarship_page:
            logger.info(
                "Source {} yielded no ranked pages; reading its entry page as one programme ({})",
                source.source_id, entry_assessment.reasons[:2],
            )
            metrics.entry_page_processed = True
            try:
                await self._process_page(
                    source, connector, entry_url, metrics, llm_client, raw_repo, mapper
                )
            except Exception as exc:  # noqa: BLE001
                metrics.errors.append(f"entry page: {exc}"[:300])
            if metrics.extraction_succeeded or metrics.scholarships_persisted:
                return []

        discover_links_from = getattr(connector, "discover_links_from", None)
        if not callable(discover_links_from):
            return []

        sections = [
            a for a in assessments
            if a.page_type == PageType.SOURCE_PAGE and a.canonical_url != entry_canonical
        ]
        # Deepest first: within a section, the deepest page is the row listing,
        # and the shallow ones are hubs that lead to it.
        sections.sort(
            key=lambda a: (-len([s for s in a.canonical_url.split("/") if s]), a.canonical_url)
        )

        deeper: list[tuple[str, str]] = []
        for section in sections[:MAX_SECTION_EXPANSIONS]:
            try:
                found = await discover_links_from(section.url)
            except Exception as exc:  # noqa: BLE001
                metrics.errors.append(f"expand {section.url}: {exc}"[:300])
                continue
            metrics.pages_fetched += 1
            metrics.expanded_section_urls.append(section.url)
            logger.info(
                "Expanded section {} of source {}: {} links",
                section.url, source.source_id, len(found),
            )
            deeper.extend(found)

        metrics.links_from_expansion = len(deeper)
        if not deeper:
            return []

        return [
            p for p in rank_candidate_urls(
                deeper, limit=max_pages, country_domain=country_domain
            )
            if (normalize_url(p.url) or p.url) != entry_canonical
        ]

    # ------------------------------------------------------------------

    def _record_signals(self, source: "SourceRegistry", url: str, signals: dict) -> None:
        """Persist page signals onto the frontier candidate for ``url``, if any.

        Best-effort by design: acquisition also runs over URLs that were never
        admitted to the frontier, and a missing candidate row is not a reason
        to fail a fetch that otherwise succeeded.
        """
        try:
            from services.exploration.repositories.frontier_repository import (
                FrontierRepository,
            )

            if source.country_id is None:
                return
            FrontierRepository(self.session).record_page_signals(
                source.country_id, url, signals
            )
        except Exception as exc:  # noqa: BLE001 — telemetry must not block ingest
            logger.debug("Could not record page signals for {}: {}", url, exc)

    def _page_intent(self, raw_doc):
        """What kind of page did we actually fetch, and what did it look like?

        V0.1 wiring of M11's classifier into the production path. The URL policy
        in `acquisition_policy` reads the *address*; this reads the page. A
        URL like ``/scholarships/xyz-2027`` can be a detail page, and a URL
        like ``/scholarship/xyz-2027`` can be a category page with a
        scholarship-shaped slug. Only the page can tell.

        Returns ``(verdict, signals, cleaned)``. The signals are the evidence
        the verdict rests on — title, link count, text length, heading count —
        so the caller can record why the page was judged as it was instead of
        leaving that reasoning only in a log line nobody reads later.

        ``cleaned`` comes back too because the listing guard downstream needs
        the real headings and anchors. Re-running the cleaner would double the
        most expensive step in the pipeline, and re-deriving counts here would
        be a second classifier.
        """
        from services.exploration.page_intent import classify_page_intent
        from services.ingestion.cleaner import clean
        from services.ingestion.loader import LoadedDocument

        document_id = str(raw_doc.document_id)
        cleaned = clean(
            LoadedDocument(
                document_id=document_id,
                source_id=str(raw_doc.source_id),
                source_url=raw_doc.source_url,
                content_type=raw_doc.content_type,
                raw_content=raw_doc.raw_content,
            )
        )
        verdict = classify_page_intent(
            url=raw_doc.source_url,
            page_title=cleaned.page_title,
            headings=cleaned.headings,
            anchors=cleaned.anchors,
            text=cleaned.clean_text,
            content_type=raw_doc.content_type,
        )
        signals = {
            "intent": verdict.intent,
            "confidence": verdict.confidence,
            "page_title": cleaned.page_title,
            "headings": len(cleaned.headings),
            "anchors": len(cleaned.anchors),
            "text_length": len(cleaned.clean_text),
            "raw_bytes": len(raw_doc.raw_content or ""),
            "document_id": document_id,
            "evidence": list(verdict.evidence[:5]),
        }
        return verdict, signals, cleaned

    def _persist_with_dedup(self, result, document_id: str):
        """Persist through the existing mapper/repository with identity dedup."""
        from services.ingestion.repositories.raw_document_repository import RawDocumentRepository

        raw_doc = RawDocumentRepository(self.session).get_by_id(document_id)
        if raw_doc is None:
            return None

        from services.scholarship import ScholarshipMapper

        # Tag the record with where it came from before mapping, so
        # provenance_origin is written by the path that produced it rather
        # than guessed later. Phase 13 depends on this being exact: an
        # exploration-discovered record must never look seed-scripted.
        extracted = result.raw_extraction.scholarship
        meta = dict(extracted.extraction_meta or {})
        meta.setdefault("origin", self.origin)
        meta.setdefault("document_id", document_id)
        extracted = extracted.model_copy(update={"extraction_meta": meta})

        mapper = ScholarshipMapper(self.session)
        try:
            scholarship = mapper.to_orm(
                extracted=extracted,
                source_id=str(raw_doc.source_id),
                document_url=raw_doc.source_url,
            )
        except ValueError as exc:
            # Missing provider/country references — extraction can't be placed.
            logger.debug("Mapping failed for doc {}: {}", document_id, exc)
            return None

        scholarship.identity_key = scholarship_identity_key(
            scholarship.provider_id, scholarship.scholarship_name, scholarship.country_id
        )

        from services.scholarship.identity import assess_duplicate

        existing = assess_duplicate(
            self.session,
            canonical_key=scholarship.identity_key,
            exclude_id=scholarship.scholarship_id,
        )
        if existing is not None:
            # One canonical row per identity: a re-discovery refreshes freshness
            # and provenance instead of creating a duplicate opportunity.
            self._merge_reacquisition(
                existing,
                scholarship,
                raw_doc.raw_content or "",
                document_id=document_id,
            )
            return None

        page_text = raw_doc.raw_content or ""
        scholarship.deadline_state = classify_deadline(
            scholarship.timeline.application_deadline if scholarship.timeline else None,
            page_text=page_text,
        )

        from services.scholarship.repository import ScholarshipRepository

        saved = ScholarshipRepository(self.session).save(scholarship)

        # Arrival is auditable, not just the decision: the record's presence
        # in the queue is itself an event with an actor.
        from database.models.scholarship_review_action import ReviewSource
        from services.review import ReviewService

        ReviewService(self.session).record_submission(
            saved,
            actor="acquisition",
            source=ReviewSource.SYSTEM,
            evidence_url=raw_doc.source_url,
        )
        return saved

    def _observed_values(self, fresh, page_text: str) -> dict:
        """What a re-discovery saw, reduced to proposable published fields.

        Only fields the reviewer could legitimately act on are collected. A
        re-crawl that changes nothing yields an empty dict, which the candidate
        path treats as "nothing to propose" rather than as a failed refresh.
        """
        fresh_tl = fresh.timeline
        observed: dict = {}

        if fresh_tl is not None:
            if fresh_tl.application_deadline is not None:
                observed["application_deadline"] = fresh_tl.application_deadline
            if fresh_tl.application_cycle:
                observed["application_cycle"] = fresh_tl.application_cycle
            if fresh_tl.application_open is not None:
                observed["application_open"] = fresh_tl.application_open

        if fresh.degree:
            observed["degree"] = fresh.degree
        if fresh.funding_type:
            observed["funding_type"] = fresh.funding_type
        if fresh.field_of_study:
            observed["field_of_study"] = list(fresh.field_of_study)

        if fresh.requirement is not None:
            for name in (
                "minimum_gpa", "ielts_required", "minimum_ielts",
                "toefl_required", "minimum_toefl",
            ):
                value = getattr(fresh.requirement, name, None)
                if value is not None:
                    observed[name] = value

        if fresh.benefit is not None:
            for name in (
                "tuition_fee", "monthly_allowance", "accommodation",
                "health_insurance", "travel_ticket", "research_grant",
            ):
                value = getattr(fresh.benefit, name, None)
                if value is not None:
                    observed[name] = value

        return observed

    def _merge_reacquisition(
        self,
        existing,
        fresh,
        page_text: str,
        *,
        document_id: str | None = None,
    ):
        """Fold a re-discovery into the canonical scholarship.

        Two paths, and the distinction between them is the M9.1 invariant:

        **Published record** — nothing is written. The observation is handed to
        ``ReviewService.propose_candidate`` and becomes a pending candidate
        revision. The scholarship stays APPROVED, stays visible, and every
        published field keeps the value a reviewer approved. A reviewer decides
        whether the fresh values replace them.

        This is the defect this fixes: the previous implementation wrote the
        fresh deadline and cycle onto the row, bumped a version, and changed
        nothing else — so published data moved with no state transition, no
        review action, and nothing a reviewer could refuse. Returning early
        instead would not be a fix either; it would silently discard the new
        source information, which is exactly what the reviewer needs to see.

        **Unpublished record** — the original merge. Safe by construction:
        ``pending_review`` data is not public, so folding in the official
        page's current cycle is curation rather than a publication bypass.
        """
        from services.review.publication import is_published

        observed = self._observed_values(fresh, page_text)

        if is_published(existing):
            # The publication boundary. Acquisition observes; ReviewService
            # decides. Nothing on the scholarship row is touched here.
            from services.review import ReviewService

            return ReviewService(self.session).propose_candidate(
                existing,
                observed=observed,
                actor="acquisition",
                origin="reacquisition",
                source_url=fresh.official_page_url or existing.official_page_url,
                raw_document_id=document_id,
                reason=(
                    "re-acquisition observed field differences; "
                    "published values unchanged pending review"
                ),
            )

        from database.models.scholarship import Scholarship
        from database.models.scholarship_version import ScholarshipVersion

        fresh_tl = fresh.timeline
        new_deadline = fresh_tl.application_deadline if fresh_tl else None
        new_cycle = fresh_tl.application_cycle if fresh_tl else None

        # Serialize against any concurrent review mutation before touching the
        # row or allocating a version. This path only runs for unpublished
        # records (approved ones became candidates in M9.1 Phase 2), but it
        # still writes to scholarship_version and would otherwise race
        # ReviewService for the same MAX(version_number). Skipping_locked is
        # deliberately NOT used here: blocking is correct, because silently
        # skipping would drop a real observation of the source.
        locked = (
            self.session.query(Scholarship)
            .filter(Scholarship.scholarship_id == existing.scholarship_id)
            .with_for_update()
            .execution_options(populate_existing=True)
            .one_or_none()
        )
        if locked is not None:
            existing = locked

        if existing.timeline is not None:
            if new_deadline:
                existing.timeline.application_deadline = new_deadline
            if new_cycle:
                existing.timeline.application_cycle = new_cycle
            effective_deadline = existing.timeline.application_deadline
        else:
            effective_deadline = new_deadline

        state = classify_deadline(effective_deadline, page_text=page_text)
        existing.deadline_state = state
        existing.last_verified_at = datetime.now(timezone.utc)

        last_no = (
            self.session.query(func.max(ScholarshipVersion.version_number))
            .filter(ScholarshipVersion.scholarship_id == existing.scholarship_id)
            .scalar()
        )
        self.session.add(
            ScholarshipVersion(
                scholarship_id=existing.scholarship_id,
                version_number=(last_no or 0) + 1,
                changed_at=datetime.now(timezone.utc),
                source_url=(fresh.official_page_url or None),
                change_summary=f"reacquired; deadline_state={state}; deadline={effective_deadline or 'none'}",
            )
        )
        self.session.flush()
        return None
