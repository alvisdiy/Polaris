"""AcquisitionService behaviour, driven through a fake connector.

`acquire_from_source` is the code that decides which pages reach the extractor,
which is the M9 fix for "we handed the ministry homepage to the extractor and
called the result a scholarship". It needs a browser to run for real, so these
tests substitute the connector and keep everything else real: the acquisition
policy, URL ranking, the ingestion pipeline, persistence and the record state
written back to the SourceRegistry row.

The properties under test are that a portal is not extracted, a programme page
is, and a failure is recorded on the source rather than swallowed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_policy import (
    AcquisitionState,
    classify_page,
    rank_candidate_urls,
)
from services.exploration.acquisition_service import AcquisitionService
from services.ingestion.connectors.base_connector import FetchResult

pytestmark = pytest.mark.integration


PROGRAMME_PAGE = """
<html><head><title>XYZ Foundation Scholarship 2027</title></head>
<body>
  <h1>XYZ Foundation Scholarship 2027</h1>
  <p>The XYZ Foundation offers this scholarship to graduate students.</p>
  <p>Applications open on 1 April 2027 and close on 15 May 2027.</p>
  <a href="https://xyz.example.org/scholarship/xyz-2027/apply">Apply now</a>
</body></html>
"""

PORTAL_PAGE = """
<html><head><title>XYZ Foundation — Scholarships</title></head>
<body><h1>Scholarships</h1><p>Number of Scholarship: 3</p></body></html>
"""

#: One programme's page reached through an opaque query URL, the shape an
#: official board uses for every notice: ``view.do?seq=759978``. The URL cannot
#: say what the page is, so the page's own text has to, exactly as a real
#: scholarship detail page does.
NEUTRAL_PROGRAMME_PAGE = """
<html><head><title>XYZ Foundation Scholarship 2027</title></head>
<body>
  <h1>XYZ Foundation Scholarship 2027</h1>
  <p>The XYZ Foundation offers this scholarship to graduate students.</p>
  <p>Eligibility: applicants must be enrolled in a master's or doctoral programme.</p>
  <p>Applications open on 1 April 2027 and close on 15 May 2027.</p>
</body></html>
"""


class FakeConnector:
    """Stands in for the Playwright connector.

    Returns a fixed link list and serves fixed HTML per URL. Records which URLs
    were fetched so the tests can assert that a portal was never fetched.
    """

    discovered: list[str] = []
    discovered_with_context: list[tuple[str, str]] | None = None
    pages: dict[str, str] = {}
    discover_error: Exception | None = None
    fetch_errors: set[str] = set()

    def __init__(self, config):
        self.config = config
        self.fetched: list[str] = []
        self.connected = False

    async def connect(self):
        self.connected = True

    async def discover(self):
        if type(self).discover_error is not None:
            raise type(self).discover_error
        return list(type(self).discovered)

    async def discover_with_context(self):
        """Mirror the real connector: pairs when the fake is given them."""
        if type(self).discover_error is not None:
            raise type(self).discover_error
        if type(self).discovered_with_context is not None:
            return list(type(self).discovered_with_context)
        return [(url, "") for url in type(self).discovered]

    async def fetch(self, url):
        self.fetched.append(url)
        if url in type(self).fetch_errors:
            raise RuntimeError(f"boom: {url}")
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
    """Install FakeConnector wherever AcquisitionService builds one."""
    FakeConnector.discovered = []
    FakeConnector.discovered_with_context = None
    FakeConnector.pages = {}
    FakeConnector.discover_error = None
    FakeConnector.fetch_errors = set()
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
        provider_code="XYZ_ACQ",
        provider_name="XYZ Foundation",
        provider_type="Foundation",
        country_id=country.country_id,
        official_url="https://xyz.example.org/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="XYZ Foundation Official Site",
        country_id=country.country_id,
        provider_id=provider.provider_id,
        official_url="https://xyz.example.org/",
        crawl_entry_url="https://xyz.example.org/",
        canonical_url="https://xyz.example.org",
        url_hash=hashlib.sha256(b"xyz-source").hexdigest(),
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    return {"session": session, "source": source, "country": country}


class TestPolicyInAcquisition:
    @pytest.mark.asyncio
    async def test_only_scholarship_pages_are_fetched(self, world, fake_connector):
        """The core Phase 8 behaviour: a portal is discovered, not extracted."""
        fake_connector.discovered = [
            "https://xyz.example.org/scholarship/xyz-2027/",
            "https://xyz.example.org/faq/",
            "https://xyz.example.org/about-us/",
            "https://xyz.example.org/news/index.html",
        ]
        fake_connector.pages = {
            "https://xyz.example.org/scholarship/xyz-2027/": PROGRAMME_PAGE
        }

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        fetched = fake_connector.instances[0].fetched
        assert fetched == ["https://xyz.example.org/scholarship/xyz-2027/"], (
            f"acquisition fetched non-scholarship pages: {fetched}"
        )
        assert metrics.scholarship_urls_found == 4
        assert metrics.pages_fetched == 1
        assert metrics.scholarships_persisted == 1

    @pytest.mark.asyncio
    async def test_portal_only_source_is_recorded_as_yielding_nothing(self, world, fake_connector):
        """A source with no programme pages is recorded, not silently empty."""
        fake_connector.discovered = [
            "https://xyz.example.org/faq/",
            "https://xyz.example.org/about-us/",
        ]
        fake_connector.pages = {}

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        assert metrics.scholarships_persisted == 0
        assert fake_connector.instances[0].fetched == []
        assert world["source"].acquisition_state == AcquisitionState.NO_SCHOLARSHIP_PAGES
        assert "none classified" in world["source"].acquisition_error

    @pytest.mark.asyncio
    async def test_off_domain_links_are_not_acquired(self, world, fake_connector):
        """A verified source must not become a crawler of unrelated sites."""
        fake_connector.discovered = [
            "https://xyz.example.org/scholarship/mine-2027/",
            "https://unrelated.com/scholarship/theirs-2027/",
        ]
        fake_connector.pages = {
            "https://xyz.example.org/scholarship/mine-2027/": PROGRAMME_PAGE
        }

        await AcquisitionService(world["session"]).acquire_from_source(world["source"])
        assert fake_connector.instances[0].fetched == [
            "https://xyz.example.org/scholarship/mine-2027/"
        ]

    @pytest.mark.asyncio
    async def test_extracted_record_carries_provenance_origin(self, world, fake_connector):
        fake_connector.discovered = ["https://xyz.example.org/scholarship/xyz-2027/"]
        fake_connector.pages = {
            "https://xyz.example.org/scholarship/xyz-2027/": PROGRAMME_PAGE
        }

        await AcquisitionService(world["session"], origin="exploration").acquire_from_source(
            world["source"]
        )

        rows = (
            world["session"]
            .query(Scholarship)
            .filter(Scholarship.source_id == world["source"].source_id)
            .all()
        )
        assert rows, "no scholarship persisted"
        # Phase 13 depends on this: an exploration-discovered record must never
        # be indistinguishable from a hand-seeded one.
        assert rows[0].provenance_origin == "exploration"

    @pytest.mark.asyncio
    async def test_arrival_is_recorded_on_the_audit_trail(self, world, fake_connector):
        from database.models.scholarship_review_action import ScholarshipReviewAction
        fake_connector.discovered = ["https://xyz.example.org/scholarship/xyz-2027/"]
        fake_connector.pages = {
            "https://xyz.example.org/scholarship/xyz-2027/": PROGRAMME_PAGE
        }

        await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        # Scoped to this source: the shared development database holds audit
        # rows from real runs, and an unscoped count would test nothing.
        rows = (
            world["session"]
            .query(ScholarshipReviewAction)
            .join(Scholarship, ScholarshipReviewAction.scholarship_id == Scholarship.scholarship_id)
            .filter(Scholarship.source_id == world["source"].source_id)
            .all()
        )
        assert [r.action for r in rows] == ["submitted"]
        assert rows[0].actor == "acquisition"


class TestFailureObservability:
    """M9 forbids silent failure: every failure must be visible somewhere."""

    @pytest.mark.asyncio
    async def test_discovery_failure_is_recorded_on_the_source(self, world, fake_connector):
        fake_connector.discover_error = RuntimeError("browser crashed")

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        assert metrics.errors
        assert world["source"].acquisition_state == AcquisitionState.FAILED
        assert "browser crashed" in world["source"].acquisition_error

    @pytest.mark.asyncio
    async def test_one_failing_page_does_not_abort_the_run(self, world, fake_connector):
        """A single bad page must not cost the pages that did work."""
        fake_connector.discovered = [
            "https://xyz.example.org/scholarship/aaa-2027/",
            "https://xyz.example.org/scholarship/zzz-2027/",
        ]
        fake_connector.pages = {
            "https://xyz.example.org/scholarship/aaa-2027/": PROGRAMME_PAGE
        }
        fake_connector.fetch_errors = {"https://xyz.example.org/scholarship/zzz-2027/"}

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        assert metrics.scholarships_persisted == 1
        assert any("zzz-2027" in e for e in metrics.errors)
        assert world["source"].acquisition_state == AcquisitionState.ACQUIRED

    @pytest.mark.asyncio
    async def test_attempts_are_counted_even_when_nothing_is_found(self, world, fake_connector):
        """Attempt count distinguishes 'never tried' from 'tried, found nothing'."""
        fake_connector.discovered = []
        await AcquisitionService(world["session"]).acquire_from_source(world["source"])
        assert world["source"].acquisition_attempts == 1
        assert world["source"].last_acquisition_at is not None

        await AcquisitionService(world["session"]).acquire_from_source(world["source"])
        assert world["source"].acquisition_attempts == 2


class TestIdentityDedup:
    @pytest.mark.asyncio
    async def test_rediscovery_collapses_instead_of_duplicating(self, world, fake_connector):
        """Two runs over the same programme must produce one scholarship."""
        fake_connector.discovered = ["https://xyz.example.org/scholarship/xyz-2027/"]
        fake_connector.pages = {
            "https://xyz.example.org/scholarship/xyz-2027/": PROGRAMME_PAGE
        }
        service = AcquisitionService(world["session"])

        first = await service.acquire_from_source(world["source"])
        assert first.scholarships_persisted == 1

        second = await service.acquire_from_source(world["source"])
        assert second.scholarships_persisted == 0
        assert second.duplicates_collapsed == 1

        # Scoped to this source; the shared database holds other countries'
        # rows that have nothing to do with this test.
        assert (
            world["session"]
            .query(Scholarship)
            .filter(Scholarship.source_id == world["source"].source_id)
            .count()
            == 1
        )


    @pytest.mark.asyncio
    async def test_url_identity_is_backfilled_onto_the_source(self, world, fake_connector):
        """A source registered before M9 gains its canonical identity.

        The backfilled canonical URL uses the same `normalize_url` contract the
        acquisition path now uses, so a bare root entry such as ``https://xyz.example.org/``
        is represented canonically as ``https://xyz.example.org``.
        """
        source = world["source"]
        source.url_hash = None
        source.canonical_url = None
        fake_connector.discovered = []
        world["session"].flush()

        await AcquisitionService(world["session"]).acquire_from_source(source)
        assert source.url_hash is not None
        assert source.canonical_url == "https://xyz.example.org/"


class TestAnchorContextReachesClassification:
    """The stage the MOFA live run lost its candidate set at.

    ``GenericPlaywrightConnector`` matched discovery keywords against the href
    alone, while ``GenericHTTPConnector`` reads the anchor text as well. The same
    entry page therefore yielded candidates over one connector and none over the
    other: an award's URL often says nothing about funding, and the link's own
    label is the only evidence the page offers.

    Anchor text is now preserved through discovery and handed to the classifier,
    which is what lets a link's label supply the evidence its URL does not. The
    ranking boundary is deliberately unchanged, and these tests pin both halves:
    the label can make a neutral programme path rankable, and it can never widen
    the boundary enough to admit a listing.
    """

    def test_anchor_text_is_what_makes_a_neutral_programme_path_rankable(self):
        """The URL alone is not enough; the label that named it is."""
        url = "https://www.example.org/grants/chevening"
        assert rank_candidate_urls([(url, "")], limit=5) == []
        labelled = rank_candidate_urls([(url, "Chevening Scholarship 2027")], limit=5)
        assert labelled, "anchor evidence was not used by the classifier"
        assert labelled[0].url == url

    def test_scholarship_shaped_url_still_ranks_without_any_anchor(self):
        """A page that is one scholarship on its own address is unaffected."""
        url = "https://www.example.org/scholarship/xyz-2027/"
        ranked = rank_candidate_urls([(url, "")], limit=5)
        assert ranked
        assert ranked[0].url == url

    def test_a_scholarship_label_cannot_rescue_a_listing(self):
        """Anchor text is evidence, not a licence to widen the boundary.

        A portal or guidance path is still rejected however its link is
        labelled; the page is a place to look, and its own links are expanded on
        a later pass instead.
        """
        listed = [
            ("https://www.example.org/news/index.html", "Scholarship news"),
            ("https://www.example.org/scholarship/how-to-apply", "How to apply for the scholarship"),
        ]
        assert rank_candidate_urls(listed, limit=5) == []

    def test_ranking_returns_only_pages_the_classifier_calls_one_scholarship(self):
        """The M9 boundary, restated over the same evidence ranking itself used.

        Every returned page must be one the classifier calls a scholarship page
        when it is given the same anchor text, which is the information ranking
        actually had. Nothing is returned on anchor evidence the classifier
        cannot see.
        """
        links = [
            ("https://www.example.org/grants/chevening", "Chevening Scholarship 2027"),
            ("https://www.example.org/news/index.html", "Scholarship news"),
            ("https://www.example.org/about/", "About us"),
        ]
        ranked = rank_candidate_urls(links, limit=5)
        anchors = dict(links)
        for page in ranked:
            assessment = classify_page(page.url, anchor_text=anchors.get(page.url, ""))
            assert assessment.is_scholarship_page, (
                f"ranked a page the classifier does not call a scholarship: {page.url}"
            )

    @pytest.mark.asyncio
    async def test_acquisition_ranks_with_the_anchor_text_discovery_provided(
        self, world, fake_connector
    ):
        """End of the wiring: a label-driven candidate reaches the extractor."""
        url = "https://xyz.example.org/grants/xyz"
        fake_connector.discovered_with_context = [(url, "XYZ Foundation Scholarship 2027")]
        fake_connector.pages = {url: NEUTRAL_PROGRAMME_PAGE}

        metrics = await AcquisitionService(world["session"]).acquire_from_source(
            world["source"]
        )

        assert fake_connector.instances[0].fetched == [url], (
            "anchor-driven candidate never reached the fetcher"
        )
        assert metrics.pages_fetched == 1
        assert metrics.scholarships_persisted == 1

    @pytest.mark.asyncio
    async def test_acquisition_does_not_fetch_a_link_the_policy_rejects(
        self, world, fake_connector
    ):
        """A link the policy rejects is still not fetched, anchors or not."""
        url = "https://xyz.example.org/board/view.do?seq=759978"
        fake_connector.discovered_with_context = [(url, "Notice")]
        fake_connector.pages = {url: NEUTRAL_PROGRAMME_PAGE}

        metrics = await AcquisitionService(world["session"]).acquire_from_source(
            world["source"]
        )

        assert fake_connector.instances[0].fetched == []
        assert metrics.scholarships_persisted == 0
        assert world["source"].acquisition_state == AcquisitionState.NO_SCHOLARSHIP_PAGES

    @pytest.mark.asyncio
    async def test_persisted_record_stays_pending_review(self, world, fake_connector):
        """Discovery reaching a page must never bypass curation."""
        url = "https://xyz.example.org/grants/xyz"
        fake_connector.discovered_with_context = [(url, "XYZ Foundation Scholarship 2027")]
        fake_connector.pages = {url: NEUTRAL_PROGRAMME_PAGE}

        await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        rows = (
            world["session"]
            .query(Scholarship)
            .filter(Scholarship.source_id == world["source"].source_id)
            .all()
        )
        assert rows, "no scholarship persisted"
        # extraction_status is the publication boundary.
        assert rows[0].extraction_status == "pending_review"
        assert rows[0].provenance_origin == "exploration"
