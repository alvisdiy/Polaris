"""The page-intent gate inside `AcquisitionService.acquire_from_source`.

V0.1 wires M11's classifier into the production acquisition path. The property
under test is not "the classifier is right" — `tests/unit/test_page_intent.py`
and `tests/integration/test_discovery_intent.py` cover that — but that the
production path *asks* and *obeys*: a page the classifier confidently calls
something other than one scholarship never reaches the extractor, a page it
cannot classify still does, and the count is reported rather than swallowed.

Every fixture below is a real page shape with a measured verdict; the URLs all
pass the pre-existing URL policy, so what is under test is the page-level gate
and not the URL-level one.

Everything except the browser is real: the classifier, the cleaner, the
pipeline, persistence and the source row.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_service import AcquisitionService
from services.ingestion.connectors.base_connector import FetchResult

pytestmark = pytest.mark.integration

# SCHOLARSHIP_DETAIL. The name is unique to this file so it cannot dedup-fold
# onto a record another suite created in the shared development database.
DETAIL_URL = "https://xyz.example.org/scholarship/ridgemount-2027/"
DETAIL_PAGE = """
<html><head><title>Ridgemount Foundation Scholarship 2027</title></head>
<body><h1>Ridgemount Foundation Scholarship 2027</h1>
<p>The Ridgemount Foundation offers this scholarship to graduate students who
have applied through the national scheme.</p>
<p>Applications open on 1 April 2027 and close on 15 May 2027.</p>
<a href="/scholarship/ridgemount-2027/apply">Apply now</a></body></html>
"""

# SCHOLARSHIP_INDEX behind a URL that reads like one award. This is the exact
# failure POST-M10 measured: the address says "scholarship", the page says "here
# are the scholarships", and extracting it produces a record named after the
# category.
INDEX_URL = "https://xyz.example.org/scholarship/xyz-2027/index.html"
INDEX_PAGE = """
<html><head><title>Ridgemount Foundation Scholarships</title></head>
<body><h1>Scholarships</h1>
<h2>Undergraduate Scholarships</h2><h2>Postgraduate Scholarships</h2>
<ul>
  <li><a href="/scholarship/aaa-2027/">AAA Scholarship</a></li>
  <li><a href="/scholarship/bbb-2027/">BBB Scholarship</a></li>
  <li><a href="/scholarship/ccc-2027/">CCC Scholarship</a></li>
  <li><a href="/scholarship/ddd-2027/">DDD Scholarship</a></li>
  <li><a href="/scholarship/eee-2027/">EEE Scholarship</a></li>
  <li><a href="/scholarship/fff-2027/">FFF Scholarship</a></li>
</ul>
<p>Application periods for each award are published below.</p></body></html>
"""

# UNIVERSITY_INFORMATION: an official page on the same host, under a URL that
# still names a scholarship year, about something else entirely.
UNIVERSITY_URL = "https://xyz.example.org/scholarship/xyz-2027/student-life.html"
UNIVERSITY_PAGE = """
<html><head><title>Student life at Ridgemount</title></head>
<body><h1>Student life</h1>
<p>Our student society runs a mentoring scheme. The scholarships office is
located in the administration building and opens during term time.</p>
</body></html>
"""

# UNKNOWN. No funding claim, no links to follow, no application wording — but
# the text is plainly about an award being made. Discarding this page would be
# discarding knowledge on the strength of silence.
QUIET_URL = "https://xyz.example.org/scholarship/quiet-2027/"
QUIET_PAGE = """
<html><body><p>Ten places are made available each year. Successful candidates
are told in the spring and take up their places from the autumn.</p></body></html>
"""

EXPECTED_INTENT = {
    DETAIL_URL: "SCHOLARSHIP_DETAIL",
    INDEX_URL: "SCHOLARSHIP_INDEX",
    UNIVERSITY_URL: "UNIVERSITY_INFORMATION",
    QUIET_URL: "UNKNOWN",
}
PAGES = {
    DETAIL_URL: DETAIL_PAGE,
    INDEX_URL: INDEX_PAGE,
    UNIVERSITY_URL: UNIVERSITY_PAGE,
    QUIET_URL: QUIET_PAGE,
}


class FakeConnector:
    discovered: list[str] = []

    def __init__(self, config):
        self.config = config

    async def connect(self):
        return None

    async def discover(self):
        return list(type(self).discovered)

    async def fetch(self, url):
        return FetchResult(
            source_id=self.config.source_id,
            raw_content=PAGES[url],
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
    FakeConnector.discovered = []
    import services.ingestion.connectors.generic_playwright as connector_module

    monkeypatch.setattr(
        connector_module, "GenericPlaywrightConnector", lambda config: FakeConnector(config)
    )
    return FakeConnector


@pytest.fixture
def world(rollback_session):
    session = rollback_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    provider = Provider(
        provider_code="XYZ_INTENT",
        provider_name="Ridgemount Foundation",
        provider_type="Foundation",
        country_id=country.country_id,
        official_url="https://xyz.example.org/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Ridgemount Official Site",
        country_id=country.country_id,
        provider_id=provider.provider_id,
        official_url="https://xyz.example.org/",
        crawl_entry_url="https://xyz.example.org/",
        canonical_url="https://xyz.example.org",
        url_hash=hashlib.sha256(b"xyz-intent-source").hexdigest(),
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    return {"session": session, "source": source}


class TestFixturesStillMeanWhatTheySay:
    """A fixture that drifts from its label makes the test below it meaningless."""

    @pytest.mark.parametrize("url", sorted(PAGES))
    def test_fixture_classifies_as_labelled(self, url):
        from services.exploration.acquisition_policy import classify_page
        from services.exploration.page_intent import classify_page_intent
        from services.ingestion.cleaner import clean
        from services.ingestion.loader import LoadedDocument

        cleaned = clean(
            LoadedDocument(
                document_id="fixture", source_id="fixture", source_url=url,
                content_type="html", raw_content=PAGES[url],
            )
        )
        verdict = classify_page_intent(
            url=url,
            page_title=cleaned.page_title,
            headings=cleaned.headings,
            anchors=cleaned.anchors,
            text=cleaned.clean_text,
        )
        assert verdict.intent == EXPECTED_INTENT[url]
        # And the URL policy must admit it, so the page-level gate is what is
        # under test rather than the URL policy quietly filtering first.
        assert classify_page(url, anchor_text="").is_scholarship_page, (
            f"{url} is filtered by the URL policy; this suite cannot see the gate"
        )


class TestPageIntentGatesExtraction:
    @pytest.mark.asyncio
    async def test_a_category_page_behind_a_detail_url_is_not_extracted(self, world, fake_connector):
        fake_connector.discovered = [INDEX_URL]

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        assert metrics.pages_fetched == 1, "the page was fetched, so the classifier got to see it"
        assert metrics.pages_skipped_not_detail == 1
        assert metrics.scholarships_persisted == 0
        assert metrics.page_intent_counts == {"SCHOLARSHIP_INDEX": 1}
        assert metrics.extraction_succeeded == 0

    @pytest.mark.asyncio
    async def test_an_official_page_about_something_else_is_not_extracted(
        self, world, fake_connector
    ):
        fake_connector.discovered = [UNIVERSITY_URL]

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        assert metrics.page_intent_counts == {"UNIVERSITY_INFORMATION": 1}
        assert metrics.pages_skipped_not_detail == 1
        assert metrics.scholarships_persisted == 0

    @pytest.mark.asyncio
    async def test_a_detail_page_still_reaches_the_extractor(self, world, fake_connector):
        fake_connector.discovered = [DETAIL_URL]

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        assert metrics.page_intent_counts == {"SCHOLARSHIP_DETAIL": 1}
        assert metrics.pages_skipped_not_detail == 0
        assert metrics.extraction_succeeded == 1
        assert metrics.scholarships_persisted == 1

    @pytest.mark.asyncio
    async def test_a_page_the_classifier_cannot_read_is_not_discarded(self, world, fake_connector):
        """UNKNOWN means "no evidence", not "evidence of nothing".

        A conservative classifier that threw away its own uncertainty would
        lose real opportunities on a signal that is silent rather than
        negative. The review queue is the safety net, so UNKNOWN is extracted.
        """
        fake_connector.discovered = [QUIET_URL]

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        assert metrics.page_intent_counts == {"UNKNOWN": 1}
        assert metrics.pages_skipped_not_detail == 0
        # The distinguishing signal: on the skip path `extraction_failed` stays
        # zero because the extractor never runs. Here it ran, saw the page and
        # found no scholarship in it — a different outcome with the same
        # "nothing persisted" result.
        assert metrics.extraction_failed == 1
        assert metrics.scholarships_persisted == 0

    @pytest.mark.asyncio
    async def test_every_fetched_page_is_counted(self, world, fake_connector):
        """Three fetched, two skipped, one extracted — and the tally adds up."""
        fake_connector.discovered = [INDEX_URL, UNIVERSITY_URL, DETAIL_URL]

        metrics = await AcquisitionService(world["session"]).acquire_from_source(world["source"])

        assert metrics.pages_fetched == 3
        assert metrics.pages_skipped_not_detail == 2
        assert metrics.scholarships_persisted == 1
        assert sum(metrics.page_intent_counts.values()) == 3


