"""V0.1.1 Step 9 — the listing guard inside the production acquisition path.

`tests/unit/test_listing_guard.py` proves the classifier's decisions. This
suite proves the property that actually closes the V0.1 ship blocker: a page it
rejects **never becomes a Scholarship row**, so it cannot reach
`ReviewService.approve` and cannot be published.

The end-to-end shape the brief requires, asserted literally:

    listing page -> detected -> no extraction -> no Scholarship row
                 -> cannot become APPROVED -> frontier records the reason

and its converse, so the guard cannot be "passing" by rejecting everything:

    legitimate detail page -> not blocked -> extraction proceeds
                           -> existing quality/review flow unchanged

Everything except the browser is real: the cleaner, the page-intent classifier,
the listing guard, the pipeline, persistence and the source row. Only the HTTP
fetch is faked, which is the same harness `test_acquisition_page_intent.py`
uses — re-using it keeps the two suites comparable instead of inventing a
second one.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_service import AcquisitionService
from services.exploration.listing_guard import ListingGuard
from services.ingestion.connectors.base_connector import FetchResult

pytestmark = pytest.mark.integration

# The aggregator shape that reached the public API in V0.1, reproduced as HTML.
# The title is a count and the body is a card list, and it still has to be
# blocked by the structural signals alone (see the "title reworded" case below).
AGGREGATOR_URL = "https://xyz.ac.uk/scholarship/xyz-2027/post-doc-scholarships/"
AGGREGATOR_PAGE = f"""
<html><head><title>190+ Post Doc scholarships 2026-27 [Updated]</title></head>
<body>
<h1>190+ Post Doc Scholarships, grants, fellowships for International Students</h1>
{"".join(f"<h2>Post Doc Scholarship programme {i} 2026</h2>" for i in range(30))}
<p>Are you eligible? Open to all nationalities. Application deadline: 15 March
2027. Eligibility criteria: you must hold a doctorate or be enrolled in a
doctoral programme. How to apply: register and submit your documents. Benefits:
monthly stipend, research allowance, travel support. Check the individual
programme page for details.</p>
<ul>
{"".join(f"<li><a href='/post-doc/scholarship-{i}/'>Scholarship programme {i}</a></li>" for i in range(30))}
</ul>
</body></html>
"""

# The marketing shape that also reached the public API in V0.1. No funding
# vocabulary anywhere on the page, and its headings are audience figures.
#
# The URL sits under a scholarship-shaped path because that is what let the
# page through in the first place: ``classify_page`` marks this a
# SCHOLARSHIP_PAGE, so the URL policy admits it and the guard is what has to
# stop it. Asserted below so the suite cannot silently start testing the URL
# policy instead of the guard.
MARKETING_URL = "https://xyz.ac.uk/scholarship/xyz-2027/recruitment-packages/"
MARKETING_PAGE = """
<html><head><title>Successful postgraduate recruitment starts with Ridgemount</title></head>
<body>
<h1>Fill your postgrad courses and raise your profile</h1>
<h2>970,000 registrants.</h2>
<h2>70% uplift.</h2>
<h2>540k magazine recipients.</h2>
<p>Postgraduate recruitment packages are a great way to engage students and
graduates with your brand. Prominent listings in our course and event searches,
email targeting and focused display advertising ensure a guaranteed response.
Our team will help you build a bespoke package.</p>
<a href="/about">About us</a>
<a href="/contact">Contact us</a>
<a href="/media">View media pack</a>
</body></html>
"""

# A single real award, behind a URL that names it. This is the converse case:
# it must still be extracted, or the guard has simply broken acquisition.
LEGITIMATE_URL = "https://xyz.ac.uk/scholarship/ridgemount-2027/"
LEGITIMATE_PAGE = """
<html><head><title>Ridgemount Foundation Scholarship 2027</title></head>
<body><h1>Ridgemount Foundation Scholarship 2027</h1>
<p>The Ridgemount Foundation offers this scholarship to graduate students who
have applied through the national scheme.</p>
<p>Applications open on 1 April 2027 and close on 15 May 2027. Tuition fees are
paid in full and a monthly stipend is provided.</p>
<a href="/scholarship/ridgemount-2027/apply">Apply now</a></body></html>
"""

PAGES = {
    AGGREGATOR_URL: AGGREGATOR_PAGE,
    MARKETING_URL: MARKETING_PAGE,
    LEGITIMATE_URL: LEGITIMATE_PAGE,
}

# Names chosen so they cannot dedup-fold onto a record another suite created in
# the shared development database.
UNIQUE_MARKERS = ("ridgemount", "post doc", "970,000")

# The deterministic extractor on this fixture cannot tell the award's degree, so
# the quality gate reports ``degree`` and blocks a bare approve. That is
# pre-existing V0.1 behaviour and is deliberately not changed here — the test
# overrides it exactly as a reviewer would, which is also what proves the
# ReviewService path is untouched.
EXPECTED_QUALITY_OVERRIDE = "degree"


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
        connector_module,
        "GenericPlaywrightConnector",
        lambda config: FakeConnector(config),
    )
    return FakeConnector


@pytest.fixture
def world(rollback_session):
    session = rollback_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    provider = Provider(
        provider_code="XYZ_GUARD",
        provider_name="Ridgemount Foundation",
        provider_type="Foundation",
        country_id=country.country_id,
        official_url="https://xyz.ac.uk/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Ridgemount Guard Source",
        country_id=country.country_id,
        provider_id=provider.provider_id,
        official_url="https://xyz.ac.uk/",
        crawl_entry_url="https://xyz.ac.uk/",
        canonical_url="https://xyz.ac.uk",
        url_hash=hashlib.sha256(b"xyz-guard-source").hexdigest(),
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    return {"session": session, "source": source, "provider": provider}


def _created_rows(session, before: set) -> list[Scholarship]:
    """Scholarship rows that appeared since ``before`` was snapshotted.

    Scoped by row id rather than by name. These integration tests share a
    development database that already holds the real V0.1 runs, including the
    actual "970,000 registrants" record this suite is named after — a
    name-based matcher would find that pre-existing row and report it as
    damage this run did. Comparing against a snapshot taken in the test itself
    is the only way to ask what *this* acquisition created.
    """
    current = set(session.execute(select(Scholarship.scholarship_id)).scalars())
    return list(
        session.execute(
            select(Scholarship).where(Scholarship.scholarship_id.in_(current - before))
        ).scalars()
    )


@pytest.fixture
def baseline(session_id_snapshot):
    return session_id_snapshot


@pytest.fixture
def session_id_snapshot(rollback_session) -> set:
    return set(
        rollback_session.execute(select(Scholarship.scholarship_id)).scalars()
    )


class TestTheUrlPolicyIsNotWhatIsUnderTest:
    @pytest.mark.parametrize("url", [AGGREGATOR_URL, MARKETING_URL, LEGITIMATE_URL])
    def test_each_page_reaches_the_fetch_stage(self, url):
        """If the URL policy filtered a page, these tests would prove nothing.

        The V0.1 failures both arrived at the pipeline, so the fixtures have to
        as well. Asserting it here means a future change to the URL policy
        cannot quietly turn this suite into a test of that instead.
        """
        from services.exploration.acquisition_policy import classify_page

        assert classify_page(url, anchor_text="").is_scholarship_page


class TestListingPagesNeverBecomeScholarshipRows:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", [AGGREGATOR_URL, MARKETING_URL])
    async def test_no_scholarship_row_is_created(
        self, world, fake_connector, session_id_snapshot, url
    ):
        fake_connector.discovered = [url]

        metrics = await AcquisitionService(world["session"]).acquire_from_source(
            world["source"]
        )

        assert metrics.pages_fetched == 1, "the page was fetched and judged"
        # Each fixture is shaped so page intent does *not* stop it — one reads
        # as DETAIL, the other as UNKNOWN, which is exactly how both escaped in
        # V0.1. So the guard is the only gate that can have fired here.
        assert metrics.pages_skipped_not_detail == 0, (
            "page intent stopped this fixture, so the guard is untested on it"
        )
        assert metrics.pages_skipped_listing == 1, (
            "the guard must be what stopped it, not the URL policy or intent"
        )
        assert metrics.extraction_succeeded == 0
        assert metrics.scholarships_persisted == 0
        assert _created_rows(world["session"], session_id_snapshot) == [], (
            "a listing page produced a Scholarship row"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", [AGGREGATOR_URL, MARKETING_URL])
    async def test_no_row_can_become_approved(
        self, world, fake_connector, session_id_snapshot, url
    ):
        """The publication boundary, asserted on the absence of a row.

        V0.1's blocker was a junk record reaching the public API. Publication
        goes through ReviewService.approve, and approve operates on a row — so
        a row that was never created cannot be approved.
        """
        fake_connector.discovered = [url]
        await AcquisitionService(world["session"]).acquire_from_source(
            world["source"]
        )

        rows = _created_rows(world["session"], session_id_snapshot)
        assert not [r for r in rows if r.extraction_status == "approved"]

    @pytest.mark.asyncio
    async def test_a_reworded_aggregator_still_produces_no_record(
        self, world, fake_connector, monkeypatch, session_id_snapshot
    ):
        """A reworded title must not be enough to let the shape through.

        Measured behaviour, and worth stating precisely: strip the count from
        the title and page intent *itself* reclassifies the page as
        SCHOLARSHIP_INDEX and stops it one step earlier than the guard. So this
        asserts the outcome — no record — rather than which gate fired, because
        asserting the guard specifically would be asserting the weaker
        boundary as the one that holds. The guard's independence from the
        title is proved at unit level
        (``test_the_both_real_failures_carry_at_least_one_independent_signal``).
        """
        reworded = AGGREGATOR_PAGE.replace(
            "190+ Post Doc scholarships 2026-27 [Updated]",
            "Study opportunities abroad",
        ).replace(
            "190+ Post Doc Scholarships, grants, fellowships for International "
            "Students",
            "Study opportunities abroad",
        )
        monkeypatch.setitem(PAGES, AGGREGATOR_URL, reworded)
        fake_connector.discovered = [AGGREGATOR_URL]

        metrics = await AcquisitionService(world["session"]).acquire_from_source(
            world["source"]
        )

        assert metrics.pages_fetched == 1
        assert metrics.extraction_succeeded == 0
        assert metrics.scholarships_persisted == 0
        # Stopped by intent, by the guard, or by both.
        assert (
            metrics.pages_skipped_not_detail + metrics.pages_skipped_listing
        ) == 1, metrics
        assert _created_rows(world["session"], session_id_snapshot) == []


class TestLegitimatePagesStillFlowThrough:
    @pytest.mark.asyncio
    async def test_a_detail_page_is_extracted_and_lands_in_review(
        self, world, fake_connector, session_id_snapshot
    ):
        """The converse. Without this the guard could pass by blocking all."""
        fake_connector.discovered = [LEGITIMATE_URL]

        metrics = await AcquisitionService(world["session"]).acquire_from_source(
            world["source"]
        )

        assert metrics.pages_skipped_listing == 0, (
            "the guard blocked a legitimate detail page"
        )
        assert metrics.extraction_succeeded == 1
        rows = _created_rows(world["session"], session_id_snapshot)
        assert len(rows) == 1
        # The guard does not approve anything. Publication stays where it was:
        # ReviewService, on a pending record.
        assert rows[0].extraction_status == "pending_review"

    @pytest.mark.asyncio
    async def test_the_review_flow_is_unchanged_for_the_legitimate_page(
        self, world, fake_connector, session_id_snapshot
    ):
        """A reviewer can still approve it — the guard is not a wall."""
        from services.review.service import ReviewService

        fake_connector.discovered = [LEGITIMATE_URL]
        await AcquisitionService(world["session"]).acquire_from_source(
            world["source"]
        )
        row = _created_rows(world["session"], session_id_snapshot)[0]

        ReviewService(world["session"]).approve(
            row.scholarship_id,
            actor="pytest",
            reason="V0.1.1 Step 9 — legitimate detail page, approved as before",
            source="manual_review",
            override_quality=True,
        )
        world["session"].flush()

        assert row.extraction_status == "approved"


class TestTheFrontierKeepsTheReason:
    @pytest.mark.asyncio
    async def test_the_candidate_row_records_the_listing_verdict(
        self, world, fake_connector
    ):
        """Step 5: the reason must survive in the existing evidence channel.

        Recording only the intent signals would leave a candidate that reads
        SCHOLARSHIP_DETAIL while having been silently dropped — invisible, and
        retryable forever.
        """
        from services.exploration.repositories.frontier_repository import (
            FrontierRepository,
        )

        session = world["session"]
        repository = FrontierRepository(session)
        row, admitted = repository.upsert_candidate(
            country_id=world["source"].country_id,
            url=AGGREGATOR_URL,
            candidate_type="opportunity",
            origin="link_expansion",
            priority=3,
        )
        assert admitted
        session.flush()

        fake_connector.discovered = [AGGREGATOR_URL]
        await AcquisitionService(session).acquire_from_source(world["source"])
        session.refresh(row)

        page_signals = (row.evidence or {}).get("page_signals", {})
        # Both halves present: what the page looked like, and why it was
        # dropped. Either alone is the failure mode.
        assert "intent" in page_signals
        guard = page_signals["listing_guard"]
        assert guard["reason"] == ListingGuard.REASON
        assert guard["verdict"] == "HIGH_CONFIDENCE_LISTING"
        assert guard["signals"]
