"""Integration test: the canonical exploration loop end-to-end.

Zero-seed country → fake search provider (local fixtures) → candidates →
analyzer (local HTML via mock) → classifier → provider resolution → authority
→ verification → source registration → acquisition pipeline → link expansion.

Uses mocked fetch/search so no live internet is needed.
"""

from dataclasses import dataclass, field

import pytest

from database.models.country import Country
from database.models.exploration_run import ExplorationRun
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.exploration.candidate_analyzer import AnalyzedCandidate, CandidateAnalyzer
from services.exploration.config_loader import load_country_config
from services.exploration.engine import CountryExplorationEngine
from services.exploration.search.base import SearchProvider, SearchQuery, SearchResult


@pytest.fixture
def session(exploration_session):
    """Rollback-only session: the engine's commits must not leak out."""
    return exploration_session


SCHOLARSHIP_PAGE_HTML = """
<html><head><title>XYZ Foundation Scholarship 2026</title></head>
<body>
<h1>XYZ Foundation Scholarship 2026</h1>
<p>The XYZ Foundation Scholarship supports international students with a
fully funded monthly stipend and tuition waiver for master programs.
Application deadline: May 1, 2027.</p>
<a href="https://official-provider.example.edu/scholarships">Official scholarship page</a>
</body></html>
"""

OFFICIAL_PAGE_HTML = """
<html><head><title>Official University Scholarships</title></head>
<body>
<h1>Scholarships for International Students</h1>
<p>Our university offers fully funded scholarships covering tuition and
stipends. Application deadline: June 15, 2027. GPA requirements apply.</p>
</body></html>
"""

JOBS_PAGE_HTML = """
<html><head><title>Germany Visa Sponsorship Farm Jobs 2026</title></head>
<body>
<h1>Farm Jobs with Visa Sponsorship</h1>
<p>We are hiring seasonal workers. Salary and employment contract included.</p>
</body></html>
"""


class FakeSearchProvider(SearchProvider):
    """Deterministic fake search results (no internet)."""

    name = "fake"

    def __init__(self, results: list[SearchResult]):
        self.results = results
        self.queries: list[str] = []

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.queries.append(query.text)
        return self.results


@dataclass
class FakeAnalyzer(CandidateAnalyzer):
    """Analyzer that returns canned pages per URL (no network)."""

    pages: dict = field(default_factory=dict)

    async def analyze(self, url: str) -> AnalyzedCandidate:  # type: ignore[override]
        result = AnalyzedCandidate(url=url)
        html = self.pages.get(url)
        if html is None:
            result.error = "http_404"
            return result
        result.fetched = True
        result.final_url = url
        result.status_code = 200
        # Reuse the real feature extractor for classifier realism
        self._extract_features(result, html)
        return result


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


DISCOVERY_URL = "https://scholarship-blog.example.net/xyz-foundation-scholarship-2026"
OFFICIAL_URL = "https://official-provider.example.edu/scholarships"
JOBS_URL = "https://jobs.example.com/germany-visa-sponsorship-farm-jobs"


@pytest.fixture
def engine(session, jp_country, monkeypatch):
    monkeypatch.setattr(
        "services.exploration.acquisition_service.AcquisitionService.acquire_from_source",
        _fake_acquire,
    )
    config = load_country_config("jp")
    config.bounds.max_pages = 20
    config.bounds.max_runtime_minutes = 1
    config.rate_limits.per_domain_delay_ms = 0
    provider = FakeSearchProvider(
        [
            SearchResult(
                url=DISCOVERY_URL,
                title="XYZ Foundation Scholarship 2026 for international students",
                snippet="fully funded scholarship for international students in Japan",
                position=1,
                provider_name="fake",
            ),
            SearchResult(url=JOBS_URL, title="Germany Visa Sponsorship Farm Jobs 2026", snippet="hiring workers", position=2, provider_name="fake"),
        ]
    )
    analyzer = FakeAnalyzer(
        pages={
            DISCOVERY_URL: SCHOLARSHIP_PAGE_HTML,
            OFFICIAL_URL: OFFICIAL_PAGE_HTML,
            JOBS_URL: JOBS_PAGE_HTML,
        }
    )
    engine = CountryExplorationEngine(session, config, provider, analyzer=analyzer)
    engine._fake_provider = provider
    return engine


async def _fake_acquire(self, source, max_pages=10):
    """Stub acquisition: pretend one scholarship was extracted and persisted."""
    from services.exploration.acquisition_service import AcquisitionMetrics

    metrics = AcquisitionMetrics()
    metrics.scholarship_urls_found = 2
    metrics.pages_fetched = 1
    metrics.extraction_succeeded = 1
    metrics.scholarships_persisted = 0
    metrics.duplicates_collapsed = 0

    # Create a real scholarship through the real pipeline pieces where cheap
    from database.models.scholarship import Scholarship as S

    existing = (
        self.session.query(S)
        .filter(S.scholarship_name == "XYZ Foundation Scholarship 2026")
        .first()
    )
    if existing is None:
        provider_row = (
            self.session.query(Provider)
            .filter(Provider.country_id == source.country_id)
            .first()
        )
        if provider_row is not None:
            scholarship = S(
                scholarship_name="XYZ Foundation Scholarship 2026",
                provider_id=provider_row.provider_id,
                country_id=source.country_id,
                source_id=source.source_id,
                official_page_url=source.official_url,
                application_url=source.official_url,
                funding_type="Fully Funded",
                extraction_status="pending_review",
            )
            self.session.add(scholarship)
            self.session.flush()
            metrics.scholarships_persisted = 1
    else:
        metrics.duplicates_collapsed = 1
    return metrics


class TestExplorationLoop:
    @pytest.mark.asyncio
    async def test_full_loop_zero_seed(self, engine, jp_country, session):
        """THE capability test: zero-seed JP through the complete loop."""
        metrics = await engine.run()

        # 1. Internet search executed. queries_executed is the true backend
        # call count, so it covers discovery plus authority-resolution queries.
        assert metrics.queries_executed > 0
        assert len(engine._fake_provider.queries) == metrics.queries_executed
        assert metrics.discovery_queries <= metrics.queries_executed
        # Authority resolution reuses the same provider, so a scholarship page
        # must push the total above the discovery query plan alone.
        assert metrics.discovery_queries < metrics.queries_executed

        # 2. Search results became frontier candidates with provenance
        assert metrics.candidates_created >= 2
        assert metrics.search_results >= 2
        # The reported distributions must add up to what was created, not be
        # empty placeholders that look like "nothing was discovered".
        assert sum(metrics.candidates_by_origin.values()) == metrics.candidates_created
        assert sum(metrics.candidates_by_type.values()) == metrics.candidates_created
        assert metrics.candidates_by_origin.get("web_search", 0) >= 2

        # 3. Pages analyzed
        assert metrics.pages_fetched >= 2

        # 4. Scholarship vs non-scholarship distinguished
        assert metrics.jobs_rejected >= 1  # farm-jobs page rejected
        assert metrics.classification_labels.get("SCHOLARSHIP", 0) >= 1

        # 5. Provider resolved from the discovery page (engine-side evidence:
        # a row count alone could be satisfied by data left over from an
        # earlier run, but resolution is per-run engine behaviour).
        assert metrics.providers_created + metrics.providers_resolved >= 1
        providers = (
            session.query(Provider)
            .filter(Provider.country_id == jp_country.country_id)
            .all()
        )
        assert len(providers) >= 1

        # 6. Authority resolution reached a verdict for every scholarship page
        verdicts = (
            metrics.authority_resolved
            + metrics.authority_candidates_found
            + metrics.authority_unresolved
        )
        assert verdicts >= 1
        assert verdicts <= sum(
            v for k, v in metrics.classification_labels.items()
            if k in ("SCHOLARSHIP", "FELLOWSHIP", "GRANT", "STUDENT_FUNDING")
        )

        # 7. Link expansion produced new candidates (official page link)
        assert metrics.link_expansions >= 1

        # 8. Provenance samples exist
        assert metrics.provenance_samples

        # 9. Frontier rows carry evidence
        from database.models.discovery_frontier import DiscoveryFrontier

        rows = (
            session.query(DiscoveryFrontier)
            .filter(DiscoveryFrontier.country_id == jp_country.country_id)
            .all()
        )
        assert rows
        with_observations = [
            r for r in rows if (r.evidence or {}).get("observations")
        ]
        assert with_observations, "every processed candidate must retain provenance"

    @pytest.mark.asyncio
    async def test_second_run_idempotent(self, engine, jp_country, session):
        """CRITICAL: second run creates no duplicate ecosystem rows."""
        await engine.run()
        providers_after_1 = session.query(Provider).count()
        sources_after_1 = session.query(SourceRegistry).count()

        await engine.run()

        providers_after_2 = session.query(Provider).count()
        sources_after_2 = session.query(SourceRegistry).count()

        # Evidence merge means no duplicate providers/sources
        assert providers_after_2 == providers_after_1
        assert sources_after_2 == sources_after_1

    @pytest.mark.asyncio
    async def test_bounded_run(self, engine, jp_country):
        engine.config.bounds.max_pages = 1  # force a tight bound
        metrics = await engine.run()
        assert metrics.pages_fetched <= 1

    @pytest.mark.asyncio
    async def test_job_page_never_becomes_scholarship(self, engine, jp_country, session):
        await engine.run()
        scholarships = (
            session.query(Scholarship)
            .filter(Scholarship.scholarship_name.ilike("%farm%"))
            .all()
        )
        assert scholarships == []

    @pytest.mark.asyncio
    async def test_duplicate_source_url_does_not_crash_run(self, engine, jp_country, session):
        """Regression: first live JP run crashed with a UniqueViolation on
        source_registry.crawl_entry_url — the pre-flush SELECT only matched
        official_url, so a row whose crawl_entry_url collided but whose
        official_url differed was invisible, and the INSERT poisoned the
        session (the run then died in the degradation handler too).
        """
        # Mirrors the live failure: existing row has a different official_url
        # but the SAME crawl_entry_url the engine is about to register.
        session.add(
            SourceRegistry(
                source_name="Official Provider Site",
                country_id=jp_country.country_id,
                official_url="https://official-provider-site.example.edu/",
                crawl_entry_url=OFFICIAL_URL,
                crawl_method="HTTP",
                crawl_frequency="monthly",
                status="Active",
                verification_state="DISCOVERED",
            )
        )
        session.flush()

        # The real verifier never reaches VERIFIED for these fake pages; force
        # it so the registration path (and its collision handling) executes.
        from services.exploration.verification_engine import STATE_VERIFIED

        class _VerifiedVerdict:
            state = STATE_VERIFIED
            confidence = 0.95
            signals = ["stub"]

        engine.verifier.verify_source = lambda *a, **k: _VerifiedVerdict()

        metrics = await engine.run()  # must not raise

        assert metrics.pages_fetched >= 1
        rows = (
            session.query(SourceRegistry)
            .filter(SourceRegistry.crawl_entry_url == OFFICIAL_URL)
            .all()
        )
        assert len(rows) == 1  # merged, not duplicated
        assert rows[0].verification_state == "VERIFIED"

        runs = (
            session.query(ExplorationRun)
            .filter(ExplorationRun.country_id == jp_country.country_id)
            .all()
        )
        assert runs and all(r.status == "completed" for r in runs)

    @pytest.mark.asyncio
    async def test_stale_running_runs_finalized_on_start(self, engine, jp_country, session):
        """Regression: killed/crashed runs left permanent RUNNING rows (two JP
        runs sat in 'running' for days). A new run must close them out."""
        from datetime import datetime, timezone

        stale = ExplorationRun(
            country_id=jp_country.country_id,
            status="running",
            config_snapshot={},
            bounds_snapshot={},
            metrics={},
            started_at=datetime.now(timezone.utc),
        )
        session.add(stale)
        session.flush()

        await engine.run()

        session.refresh(stale)
        assert stale.status == "failed"
        assert stale.finished_at is not None
