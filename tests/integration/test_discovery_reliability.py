"""Regression tests for the 2026-10 discovery failures.

Four verified official sources were fetched successfully and produced nothing.
None of them failed in the extractor. Each died at a different stage of the same
path, and each stage is pinned here:

===================================  ==========================================
source                               stage that lost the candidate
===================================  ==========================================
DAAD                                  classification: a year-less programme page
                                      scored 0.40 and stayed a SOURCE_PAGE
University of Tsukuba                 extraction: 1,415 record links carried no
                                      keyword; discovery was one level deep and
                                      the listing renders after domcontentloaded
MOFA Korea (embassy boards)           acquisition: the entry URL *is* the
                                      announcement and was never read as one
===================================  ==========================================

The tests are split by layer so a future failure says which layer broke:

* classification — what a URL is (pure function, no network)
* extraction     — which links a page offers (DOM parsing, no browser)
* acquisition    — what reaches the review queue (fake connector, real pipeline)
* render wait    — how long the browser waits before reading the DOM
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_review_action import ScholarshipReviewAction
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_policy import (
    AcquisitionState,
    PageType,
    classify_page,
    is_detail_record_url,
    rank_candidate_urls,
)
from services.exploration.acquisition_service import AcquisitionService
from services.ingestion.connectors.base_connector import ConnectorConfig, FetchResult
from services.ingestion.connectors.generic_playwright import (
    DEFAULT_RENDER_WAIT_MS,
    GenericPlaywrightConnector,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# 1. Classification: what a URL is
# ---------------------------------------------------------------------------


class TestNamedProgrammeClassification:
    """DAAD: 6 links found, 0 ranked.

    Every DAAD programme page is reached from a category index
    (``/scholarships/``) with a slug that names the programme and no intake
    year (``/scholarships/daad-funding-programme``). The classifier could only
    award 0.40 for "scholarship noun in the final segment", which is
    deliberately below the 0.60 threshold, so all six were counted as source
    pages and dropped. The threshold is unchanged; what the classifier can now
    express is the difference between a segment that *names a programme* and
    one that names a collection.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.daad.de/en/studying-in-germany/scholarships/daad-funding-programme/",
            "https://www.daad.de/en/studying-in-germany/scholarships/helmut-schmidt-programme/",
            "https://www.daad.de/en/studying-in-germany/scholarships/short-term-scholarship/",
        ],
    )
    def test_year_less_programme_page_is_a_scholarship_page(self, url):
        assessment = classify_page(url)
        assert assessment.page_type == PageType.SCHOLARSHIP_PAGE, assessment.reasons
        assert assessment.confidence >= 0.6
        assert "final segment names one programme" in " ".join(assessment.reasons)

    @pytest.mark.parametrize(
        "url",
        [
            # A collection: one token, the plural noun itself.
            "https://www.daad.de/en/studying-in-germany/scholarships/",
            # A category inside the collection.
            "https://www.daad.de/en/studying-in-germany/scholarships/funding-options/",
            "https://www.daad.de/en/studying-in-germany/scholarships/music-art/",
            # A named programme *and* portal vocabulary.
            "https://www.daad.de/en/studying-in-germany/scholarships/programme-index/",
            # A section that collects programmes, reachable on a real
            # university site. It contains a programme head and is *not* a
            # programme; promoting it is the failure this rule must not have.
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/",
        ],
    )
    def test_collections_and_categories_stay_source_pages(self, url):
        assessment = classify_page(url)
        assert assessment.page_type == PageType.SOURCE_PAGE, (url, assessment.reasons)
        assert rank_candidate_urls([(url, "")], limit=5) == []

    def test_apply_page_that_names_a_scholarship_stays_a_process_page(self):
        """`/apply-for-a-scholarship` names a scholarship and is not one.

        This URL is real (USC Foundation) and was a SOURCE_PAGE before the
        named-programme tier existed; the tier must not promote it.
        """
        assessment = classify_page("https://www.uscifoundation.org/apply-for-a-scholarship")
        assert not assessment.is_scholarship_page, assessment.reasons

    def test_programme_page_with_an_intake_year_is_unchanged(self):
        """The new tier is additive: year-based pages rank exactly as before."""
        assessment = classify_page(
            "https://www.studyinjapan.go.jp/en/scholarship/monbukagakusho-2027/"
        )
        assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
        assert assessment.confidence == pytest.approx(0.6)


class TestProviderHintWordBoundary:
    """A path hint must match a word, not a fragment of one.

    ``/en/admissions/`` was taxed 0.20 as an organisation page because
    "admissions" contains "mission". The same collision applies to
    "commission", "permission" and "submission" — words that appear in the
    paths of pages that publish scholarship announcements.
    """

    def test_admissions_is_not_an_organisation_page(self):
        assessment = classify_page(
            "https://www.tsukuba.ac.jp/en/admissions/undergraduate/"
        )
        assert "path describes the organisation" not in " ".join(assessment.reasons)

    def test_a_real_organisation_page_still_is(self):
        assessment = classify_page("https://www.mofa.go.jp/about/contact/")
        assert "path describes the organisation" in " ".join(assessment.reasons)

    def test_penalty_is_still_applied_to_a_scholarship_page_under_about(self):
        """The penalty must still be able to change a verdict."""
        assessment = classify_page("https://example.edu/about/scholarship/")
        assert not assessment.is_scholarship_page


class TestRecordUrlRecognition:
    """The URL shapes that carry no keyword at all."""

    @pytest.mark.parametrize(
        "url",
        [
            # 1,415 of these on one Tsukuba listing.
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/2026917.html",
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/fg202610135.html",
            # The MOFA Korea board/article shape.
            "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759978",
            "https://www.mofa.go.kr/kh-en/brd/m_25856/view.do?seq=66",
        ],
    )
    def test_record_urls_are_recognised(self, url):
        assert is_detail_record_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.mofa.go.kr/il-en/index.do",
            "https://www.mofa.go.kr/il-en/brd/m_11417/list.do",
            "https://www.tsukuba.ac.jp/en/admissions/",
            "https://www.daad.de/en/studying-in-germany/scholarships/",
            # A search results view, not one record.
            "https://example.edu/search?seq=12&q=scholarship&page=2",
            # An id of one digit is a page number far more often than a record.
            "https://example.edu/news/page/2.html",
        ],
    )
    def test_non_record_urls_are_not_recognised(self, url):
        assert not is_detail_record_url(url)

    def test_record_url_inside_a_scholarship_section_is_eligible(self):
        """Tsukuba's records: the path names the section, the id names the row."""
        url = (
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/"
            "scholarship-links/pg/2026917.html"
        )
        assessment = classify_page(url)
        assert assessment.page_type == PageType.SCHOLARSHIP_PAGE, assessment.reasons
        assert rank_candidate_urls([(url, "")], limit=5)

    def test_mofa_board_record_ranks_only_with_a_scholarship_label(self):
        url = "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759978"
        assert not classify_page(url).is_scholarship_page
        labelled = classify_page(
            url, anchor_text="2026 Global Korea Scholarship (GKS) Application Guidelines"
        )
        assert labelled.page_type == PageType.SCHOLARSHIP_PAGE, labelled.reasons


# ---------------------------------------------------------------------------
# 2. Extraction: which links a page offers
# ---------------------------------------------------------------------------


def _connector(url: str, **custom):
    return GenericPlaywrightConnector(
        ConnectorConfig(source_id=uuid.uuid4(), url=url, custom_settings=custom)
    )


TSUKUBA_LISTING_HTML = """
<html><head><title>奨学団体一覧</title></head>
<body>
  <div class="list">
    <a href="2026917.html">(一社)ことば・みらい・スカラシップ　2026</a>
    <a href="2026918.html">日本学生支援機構 奨学金</a>
    <a href="index.html">トップ</a>
    <a href="/sitepolicy/">このサイトについて</a>
    <a href="/about/">大学案内</a>
  </div>
</body></html>
"""


class TestRecordLinkExtraction:
    """Tsukuba: the rows exist in the DOM but none carried a keyword.

    Discovery matched ``DEFAULT_DISCOVERY_KEYWORDS`` against the href and the
    anchor. A foundation's Japanese name and an id-shaped URL contain none of
    them, so a listing of 1,415 programmes produced zero candidates.
    """

    def test_record_links_are_admitted_without_a_keyword(self):
        connector = _connector(
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/index.html"
        )
        found = connector._extract_candidate_links_with_context(
            TSUKUBA_LISTING_HTML,
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/index.html",
        )
        urls = [url for url, _anchor in found]

        assert "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/2026917.html" in urls
        assert "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/2026918.html" in urls
        # Navigation is still not a candidate, record shapes or not.
        assert not any(u.endswith("/sitepolicy/") for u in urls)
        assert not any(u.endswith("/about/") for u in urls)
        # The listing page itself is admitted by the *keyword* gate that was
        # already there (its path contains "scholarship"). What must hold is
        # that it is not a scholarship page once classified.
        ranked = rank_candidate_urls(found, limit=10)
        assert not any(p.url.endswith("index.html") for p in ranked)

    def test_the_label_travels_with_the_record(self):
        """Ranking needs the label; a bare URL cannot say what a record is."""
        connector = _connector(
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/index.html"
        )
        pairs = connector._extract_candidate_links_with_context(
            TSUKUBA_LISTING_HTML,
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/index.html",
        )
        label = dict(pairs)[
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/2026917.html"
        ]
        assert "スカラシップ" in label

    def test_admitted_records_still_have_to_survive_ranking(self):
        """The gate widened by one shape; the eligibility rule did not move."""
        connector = _connector(
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/index.html"
        )
        pairs = connector._extract_candidate_links_with_context(
            TSUKUBA_LISTING_HTML,
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/index.html",
        )
        ranked = rank_candidate_urls(pairs, limit=10)
        # Both records are inside a scholarship section and carry an intake
        # year in the anchor or the id, so both are one programme.
        assert len(ranked) == 2, [p.url for p in ranked]
        assert all(p.score >= 0.6 for p in ranked)
        assert all("index.html" not in p.url for p in ranked)


# ---------------------------------------------------------------------------
# 3. Render wait: how long the browser waits before reading the DOM
# ---------------------------------------------------------------------------


class _FakePage:
    def __init__(self, idle: bool):
        self.idle = idle
        self.waited = None

    async def wait_for_load_state(self, state, timeout=None):
        self.waited = (state, timeout)
        if not self.idle:
            raise TimeoutError("page never went idle")


class TestBoundedRenderWait:
    def test_settle_waits_for_the_network_to_go_quiet(self):
        connector = _connector("https://example.edu/")
        page = _FakePage(idle=True)

        import asyncio

        asyncio.run(connector._settle(page))
        assert page.waited == ("networkidle", DEFAULT_RENDER_WAIT_MS)

    def test_a_page_that_never_idles_does_not_fail_the_fetch(self):
        """A streaming or polling page must not become a timeout."""
        connector = _connector("https://example.edu/")
        page = _FakePage(idle=False)

        import asyncio

        asyncio.run(connector._settle(page))  # must not raise

    def test_wait_can_be_disabled_per_source(self):
        connector = _connector("https://example.edu/", render_wait_ms=0)
        page = _FakePage(idle=True)

        import asyncio

        asyncio.run(connector._settle(page))
        assert page.waited is None


# ---------------------------------------------------------------------------
# 4. Acquisition: what reaches the review queue
# ---------------------------------------------------------------------------

PROGRAMME_PAGE = """
<html><head><title>XYZ Foundation Scholarship 2027</title></head>
<body>
  <h1>XYZ Foundation Scholarship 2027</h1>
  <p>The XYZ Foundation offers this scholarship to graduate students.</p>
  <p>Eligibility: applicants must be enrolled in a master's or doctoral programme.</p>
  <p>Applications open on 1 April 2027 and close on 15 May 2027.</p>
</body></html>
"""

PERIODIC_PROGRAMME_PAGE = """
<html><head><title>XYZ Foundation Scholarship for Scientific Research 2027</title></head>
<body>
  <h1>XYZ Foundation Scholarship for Scientific Research 2027</h1>
  <p>The XYZ Foundation offers this scholarship to doctoral candidates.</p>
  <p>Eligibility: applicants must hold a master's degree.</p>
  <p>The application deadline is 30 June 2027.</p>
</body></html>
"""

PORTAL_INDEX_PAGE = """
<html><head><title>Scholarships</title></head>
<body>
  <h1>Scholarships</h1>
  <p>This page lists the scholarships available to international students.</p>
  <a href="/scholarship/section/">By programme</a>
  <a href="/scholarship/notice/">Notices</a>
</body></html>
"""


class FakeConnector:
    """Stands in for the Playwright connector.

    Serves links for the configured entry URL and for any page asked about
    through ``discover_links_from``, and HTML for every page fetched. Records
    each call so a test can assert what was navigated and what was not.
    """

    entry_links: list[tuple[str, str]] = []
    section_links: dict[str, list[tuple[str, str]]] = {}
    pages: dict[str, str] = {}
    instances: list = []

    def __init__(self, config):
        self.config = config
        self.fetched: list[str] = []
        self.expanded: list[str] = []

    async def connect(self):
        return None

    async def discover(self):
        return [url for url, _ in type(self).entry_links]

    async def discover_with_context(self):
        return list(type(self).entry_links)

    async def discover_links_from(self, url):
        self.expanded.append(url)
        return list(type(self).section_links.get(url, []))

    async def fetch(self, url):
        self.fetched.append(url)
        html = type(self).pages.get(url)
        if html is None:
            raise RuntimeError(f"no fake page for {url}")
        return FetchResult(
            source_id=self.config.source_id,
            raw_content=html,
            content_type="html",
            final_url=url,
            status_code=200,
            processing_time_ms=1.0,
            retry_count=0,
            crawl_time=datetime.now(timezone.utc),
        )

    async def close(self):
        return None


@pytest.fixture
def fake_connector(monkeypatch):
    FakeConnector.entry_links = []
    FakeConnector.section_links = {}
    FakeConnector.pages = {}
    FakeConnector.instances = []

    import services.ingestion.connectors.generic_playwright as connector_module

    def factory(config):
        instance = FakeConnector(config)
        FakeConnector.instances.append(instance)
        return instance

    monkeypatch.setattr(connector_module, "GenericPlaywrightConnector", factory)
    return FakeConnector


@pytest.fixture
def world(rollback_session):
    session = rollback_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    provider = Provider(
        provider_code="XYZ_DISCOVERY",
        provider_name="XYZ Foundation",
        provider_type="Foundation",
        country_id=country.country_id,
        official_url="https://xyz.example.org/",
        verification_status="verified",
    )
    session.add(provider)
    session.flush()
    return {"session": session, "country": country, "provider": provider}


def _scholarships(world):
    """This test's records only. The development database is not empty."""
    return world["session"].query(Scholarship).filter(
        Scholarship.provider_id == world["provider"].provider_id
    )


def _review_actions(world):
    scholarship_ids = [s.scholarship_id for s in _scholarships(world).all()]
    return world["session"].query(ScholarshipReviewAction).filter(
        ScholarshipReviewAction.scholarship_id.in_(scholarship_ids)
    )


def _source(world, *, entry_url: str, name: str) -> SourceRegistry:
    source = SourceRegistry(
        source_name=name,
        country_id=world["country"].country_id,
        provider_id=world["provider"].provider_id,
        official_url=entry_url,
        crawl_entry_url=entry_url,
        canonical_url=entry_url,
        url_hash=hashlib.sha256(entry_url.encode()).hexdigest(),
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    world["session"].add(source)
    world["session"].flush()
    return source


class TestZeroYieldRecoveryTwoLevelPortal:
    """Tsukuba: the entry page lists sections, the records are one level down.

    Before this fix the run ended at zero: the entry page's links were all
    section pages (correctly, not scholarships), discovery stopped there, and
    the source was recorded as yielding nothing.
    """

    @pytest.mark.asyncio
    async def test_records_one_level_below_reach_the_review_queue(
        self, world, fake_connector
    ):
        entry = "https://xyz.example.org/campuslife/support-scholarship/"
        section = "https://xyz.example.org/campuslife/support-scholarship/pg/index.html"
        record = "https://xyz.example.org/campuslife/support-scholarship/pg/2026917.html"

        fake_connector.entry_links = [(section, "民間奨学団体")]
        fake_connector.section_links = {
            section: [(record, "XYZ Foundation Scholarship 2027")]
        }
        fake_connector.pages = {record: PROGRAMME_PAGE}

        source = _source(world, entry_url=entry, name="XYZ University Scholarships")
        metrics = await AcquisitionService(world["session"]).acquire_from_source(source)

        instance = fake_connector.instances[-1]
        assert instance.expanded == [section]
        assert instance.fetched == [record]
        assert metrics.links_from_expansion == 1
        assert metrics.expanded_section_urls == [section]
        assert metrics.scholarships_persisted == 1

        saved = _scholarships(world).one()
        assert saved.extraction_status == "pending_review"
        assert saved.provenance_origin == "exploration"
        assert source.acquisition_state == AcquisitionState.ACQUIRED

    @pytest.mark.asyncio
    async def test_recovery_does_not_expand_when_ranking_already_yielded_pages(
        self, world, fake_connector
    ):
        """The extra navigations are a zero-yield fallback, not a default."""
        entry = "https://xyz.example.org/"
        programme = "https://xyz.example.org/scholarship/xyz-2027/"
        section = "https://xyz.example.org/scholarship/index.html"

        fake_connector.entry_links = [
            (programme, "XYZ Scholarship 2027"),
            (section, "All scholarships"),
        ]
        fake_connector.section_links = {section: [(programme, "XYZ Scholarship 2027")]}
        fake_connector.pages = {programme: PROGRAMME_PAGE}

        source = _source(world, entry_url=entry, name="XYZ Foundation Official Site")
        metrics = await AcquisitionService(world["session"]).acquire_from_source(source)

        assert fake_connector.instances[-1].expanded == []
        assert metrics.expanded_section_urls == []
        assert metrics.scholarships_persisted == 1

    @pytest.mark.asyncio
    async def test_expansion_is_bounded_and_not_repeated_on_a_second_run(
        self, world, fake_connector
    ):
        """A second run must not create a second record or a second review action."""
        entry = "https://xyz.example.org/campuslife/support-scholarship/"
        section = "https://xyz.example.org/campuslife/support-scholarship/pg/index.html"
        record = "https://xyz.example.org/campuslife/support-scholarship/pg/2026917.html"

        fake_connector.entry_links = [(section, "民間奨学団体")]
        fake_connector.section_links = {section: [(record, "XYZ Foundation Scholarship 2027")]}
        fake_connector.pages = {record: PROGRAMME_PAGE}

        source = _source(world, entry_url=entry, name="XYZ University Scholarships")
        service = AcquisitionService(world["session"])
        await service.acquire_from_source(source)
        second = await service.acquire_from_source(source)

        assert _scholarships(world).count() == 1
        actions = _review_actions(world).all()
        assert len(actions) == 1
        assert actions[0].action == "submitted"
        assert actions[0].new_state == "pending_review"
        assert second.duplicates_collapsed == 1
        assert second.scholarships_persisted == 0


class TestEntryPageThatIsOneProgramme:
    """MOFA Korea: the source's entry URL *is* one announcement.

    The entry page was never read as one opportunity, so discovery could only
    report its outbound links — and a board record has few, none labelled with
    a scholarship. The source ended at zero with nothing persisted.
    """

    @pytest.mark.asyncio
    async def test_entry_page_is_persisted_when_its_own_name_is_a_scholarship(
        self, world, fake_connector
    ):
        entry = "https://xyz.example.org/brd/m_11417/view.do?seq=759978"
        fake_connector.entry_links = [
            ("https://xyz.example.org/brd/m_11417/list.do", "목록"),
        ]
        fake_connector.pages = {entry: PROGRAMME_PAGE}

        source = _source(
            world,
            entry_url=entry,
            name="2026 Global Korea Scholarship (GKS) Application Guidelines",
        )
        metrics = await AcquisitionService(world["session"]).acquire_from_source(source)

        assert metrics.entry_page_processed is True
        assert fake_connector.instances[-1].fetched == [entry]
        assert metrics.scholarships_persisted == 1
        saved = _scholarships(world).one()
        assert saved.extraction_status == "pending_review"

    @pytest.mark.asyncio
    async def test_an_entry_page_whose_body_is_an_index_is_still_not_extracted(
        self, world, fake_connector
    ):
        """The recovery path must not become a way to extract a portal.

        The URL says "one programme" and so does the source's name, which is
        what puts the entry page on the recovery path. The page's own content
        says it is an index, and that verdict is the one that decides.
        """
        entry = "https://xyz.example.org/scholarship/programme-2027/"
        fake_connector.entry_links = [
            ("https://xyz.example.org/notice/board/", "Notice"),
        ]
        fake_connector.pages = {entry: PORTAL_INDEX_PAGE}

        source = _source(world, entry_url=entry, name="XYZ Scholarship Programme 2027")
        metrics = await AcquisitionService(world["session"]).acquire_from_source(source)

        assert metrics.entry_page_processed is True
        assert _scholarships(world).count() == 0
        assert metrics.scholarships_persisted == 0
        assert metrics.pages_skipped_not_detail == 1
        assert source.acquisition_state == AcquisitionState.NO_SCHOLARSHIP_PAGES
        # The recorded error has to say where the run looked.
        assert "entry page processed as one opportunity: True" in source.acquisition_error

    @pytest.mark.asyncio
    async def test_a_portal_entry_page_is_never_fetched_for_recovery(
        self, world, fake_connector
    ):
        """A source whose entry is plainly an index is not fetched again.

        The fallback is conditional on the entry URL and the source's own name
        describing one programme. Without that evidence there is nothing to
        read, and the extra fetch is not spent.
        """
        entry = "https://xyz.example.org/scholarship/"
        fake_connector.entry_links = [
            ("https://xyz.example.org/scholarship/notice/", "Notices"),
        ]
        fake_connector.pages = {entry: PORTAL_INDEX_PAGE}

        source = _source(world, entry_url=entry, name="XYZ Foundation Scholarships")
        metrics = await AcquisitionService(world["session"]).acquire_from_source(source)

        assert metrics.entry_page_processed is False
        assert entry not in fake_connector.instances[-1].fetched
        assert _scholarships(world).count() == 0
        assert source.acquisition_state == AcquisitionState.NO_SCHOLARSHIP_PAGES


class TestStageMetrics:
    """A failure has to be diagnosable from the metrics alone."""

    @pytest.mark.asyncio
    async def test_every_discovered_link_is_counted_by_verdict(self, world, fake_connector):
        entry = "https://xyz.example.org/"
        programme = "https://xyz.example.org/scholarship/xyz-2027/"
        fake_connector.entry_links = [
            (programme, "XYZ Scholarship 2027"),
            ("https://xyz.example.org/scholarship/", "All scholarships"),
            ("https://xyz.example.org/scholarship/how-to-apply", "How to apply"),
            ("https://xyz.example.org/faq/", "FAQ"),
        ]
        fake_connector.pages = {programme: PERIODIC_PROGRAMME_PAGE}

        source = _source(world, entry_url=entry, name="XYZ Foundation Official Site")
        metrics = await AcquisitionService(world["session"]).acquire_from_source(source)

        assert metrics.links_extracted == 4
        assert sum(metrics.candidates_by_page_type.values()) == 4
        assert metrics.candidates_by_page_type[PageType.SCHOLARSHIP_PAGE] == 1
        assert metrics.rejection_reasons
        # Every rejection names the verdict and the reason it was reached.
        assert all(
            key.split(":")[0] in {
                PageType.SOURCE_PAGE,
                PageType.OTHER_OFFICIAL_PAGE,
                PageType.PROVIDER_PAGE,
            }
            for key in metrics.rejection_reasons
        )
