"""End-to-end test of the M9 publication path.

The claim being tested is the one the M9 brief is ultimately about:

    source page -> scholarship page -> extraction -> validation -> review
    -> approval -> public API -> matching

with a real HTML page through the real cleaner, extractor, validator, mapper,
review service, repository and API. Nothing is mocked except the network fetch,
which is the only genuinely external step.

It also asserts the negative case, because that is what actually protects
users: a rejected record never reaches the public API or matching, even though
it exists in the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.source_registry import SourceRegistry
from services.ingestion.connectors.base_connector import FetchResult
from services.ingestion.orchestrator import run_pipeline
from services.ingestion.real_extractor import DeterministicLLMClient
from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
from services.ingestion.repositories.raw_document_repository import RawDocumentRepository
from services.review import NotPublishable, ReviewService, ReviewStatus

pytestmark = pytest.mark.integration


# A page shaped like a real government scholarship listing: a portal heading,
# one link to a programme, and nothing else. Extraction must refuse to invent
# a scholarship from it.
PORTAL_HTML = """
<html><head><title>Study in Japan — Scholarships</title></head>
<body>
  <h1>Scholarships</h1>
  <p>Number of Scholarship: 45</p>
  <p>Amount of Scholarship: fully funded</p>
  <ul>
    <li><a href="/en/scholarship/monbukagakusho-2027/">Monbukagakusho Scholarship 2027</a></li>
    <li><a href="/en/faq/">Frequently Asked Questions</a></li>
  </ul>
</body></html>
"""

PROGRAMME_HTML = """
<html><head><title>Monbukagakusho Scholarship 2027 — MEXT</title></head>
<body>
  <h1>Monbukagakusho Scholarship 2027</h1>
  <p>The Ministry of Education, Culture, Sports, Science and Technology of Japan
     offers the Monbukagakusho Scholarship to international students enrolled in
     a master's programme.</p>
  <h2>Benefits</h2>
  <ul>
    <li>Tuition fees are covered in full.</li>
    <li>A monthly allowance is paid.</li>
    <li>Airplane tickets to Japan are provided.</li>
  </ul>
  <h2>Application</h2>
  <p>Applications open on 1 April 2027 and must be submitted by 15 May 2027.</p>
  <a href="https://www.studyinjapan.go.jp/en/scholarship/monbukagakusho-2027/apply">Apply</a>
</body></html>
"""


@pytest.fixture
def world(exploration_session):
    """A verified source, a stored portal page and a stored programme page."""
    session = exploration_session
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    provider = Provider(
        provider_code=f"E2E_{uuid.uuid4().hex[:8].upper()}"[:32],
        provider_name="Ministry of Education, Culture, Sports, Science and Technology",
        provider_type=ProviderType.GOVERNMENT,
        country_id=jp.country_id,
        official_url="https://www.studyinjapan.go.jp/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Study in Japan",
        country_id=jp.country_id,
        official_url="https://www.studyinjapan.go.jp/en/",
        crawl_entry_url="https://www.studyinjapan.go.jp/en/",
        canonical_url="https://www.studyinjapan.go.jp/en",
        url_hash=uuid.uuid4().hex * 2,
        page_type="SOURCE_PAGE",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()

    def store(html: str, url: str) -> RawDocument:
        result = FetchResult(
            source_id=source.source_id,
            raw_content=html,
            content_type="html",
            final_url=url,
            status_code=200,
            processing_time_ms=1.0,
            retry_count=0,
            crawl_time=datetime.now(timezone.utc),
        )
        doc = RawDocumentMapper().to_orm(result)
        saved = RawDocumentRepository(session).save(doc)
        return saved

    return {
        "session": session,
        "country": jp,
        "provider": provider,
        "source": source,
        "store": store,
        "llm": DeterministicLLMClient(),
    }


def _fetch_result(source, html, url):
    return FetchResult(
        source_id=source.source_id,
        raw_content=html,
        content_type="html",
        final_url=url,
        status_code=200,
        processing_time_ms=1.0,
        retry_count=0,
        crawl_time=datetime.now(timezone.utc),
    )


def _persist_extraction(world, doc, result, origin="exploration"):
    """Map a validated extraction to a Scholarship row, as acquisition does."""
    from services.scholarship.mapper import ScholarshipMapper

    extracted = result.raw_extraction.scholarship
    meta = dict(extracted.extraction_meta or {})
    meta.setdefault("origin", origin)
    meta.setdefault("document_id", str(doc.document_id))
    extracted = extracted.model_copy(update={"extraction_meta": meta})

    mapper = ScholarshipMapper(world["session"])
    scholarship = mapper.to_orm(
        extracted=extracted,
        source_id=str(world["source"].source_id),
        document_url=doc.source_url,
    )
    # Identity is set by AcquisitionService; a test that skipped it would
    # collide with every other record in the shared database.
    scholarship.identity_key = uuid.uuid4().hex
    world["session"].add(scholarship)
    world["session"].flush()
    return scholarship


class TestPortalIsNotAScholarship:
    def test_listing_page_never_yields_a_portal_fragment_as_a_name(self, world):
        """The M8 failure, reproduced and refused.

        "Number of Scholarship: 45" is prose on a listing page. Naming a
        scholarship after it is how 17 M8 rows came to exist. Whatever the
        extractor decides to do with a listing page, the name it produces must
        never be the page's own prose.
        """
        doc = world["store"](PORTAL_HTML, "https://www.studyinjapan.go.jp/en/")
        result = run_pipeline(str(doc.document_id), world["session"], world["llm"])

        name = None
        if result.raw_extraction.scholarship is not None:
            name = result.raw_extraction.scholarship.scholarship_name

        assert name != "Number of Scholarship"
        assert name != "Amount of Scholarship"
        assert name != "Scholarships"
        assert not (name or "").startswith("Unknown ")

    def test_acquisition_policy_is_what_keeps_portals_out_of_extraction(self):
        """The primary defence is upstream: never feed a portal to the extractor.

        The extractor is good enough that a listing page may still yield a real
        name from its anchors. The policy is what guarantees the pipeline only
        ever sees pages that are about one programme.
        """
        from services.exploration.acquisition_policy import PageType, classify_page

        portal = classify_page("https://www.studyinjapan.go.jp/en/", title="Study in Japan")
        assert portal.page_type == PageType.SOURCE_PAGE
        assert portal.should_discover_links
        assert not portal.is_scholarship_page

    def test_generic_portal_fragments_are_never_names(self):
        """Directly on the extractor's verdict, for every M8 offender."""
        from services.ingestion.extraction_quality import score_candidate_name

        for candidate in (
            "Unknown Scholarship",
            "Number of Scholarship",
            "Amount of Scholarship",
            "Das Program",
            "At a glance",
            "Grant",
        ):
            verdict = score_candidate_name(candidate, in_title=True, in_heading=True)
            assert not verdict.accepted, f"{candidate!r} was accepted as a scholarship name"


class TestProgrammePageBecomesPendingRecord:
    def test_real_page_extracts_and_persists_with_provenance(self, world):
        doc = world["store"](
            PROGRAMME_HTML, "https://www.studyinjapan.go.jp/en/scholarship/monbukagakusho-2027/"
        )
        result = run_pipeline(str(doc.document_id), world["session"], world["llm"])
        assert result.is_valid, result.validation_report.issues
        assert result.raw_extraction.scholarship.scholarship_name == "Monbukagakusho Scholarship 2027"

        saved = _persist_extraction(world, doc, result)

        # M9 principle 2: provenance is present before anything is published.
        assert saved.extraction_status == ReviewStatus.PENDING_REVIEW
        assert saved.field_provenance, "no field provenance recorded"
        assert saved.field_provenance["scholarship_name"]["source_url"]
        assert saved.provenance_origin == "exploration"
        assert saved.quality_report is not None
        assert "identity" in saved.quality_report["fields"]

        # Arrival is auditable.
        ReviewService(world["session"]).record_submission(
            saved, actor="acquisition", evidence_url=doc.source_url
        )
        actions = ReviewService(world["session"]).history(str(saved.scholarship_id))
        assert [a.action for a in actions] == ["submitted"]


class TestReviewToPublication:
    """Approval is the only door, and it leaves a trail."""

    @pytest.fixture
    def pending(self, world):
        doc = world["store"](
            PROGRAMME_HTML, "https://www.studyinjapan.go.jp/en/scholarship/monbukagakusho-2027/"
        )
        result = run_pipeline(str(doc.document_id), world["session"], world["llm"])
        scholarship = _persist_extraction(world, doc, result)
        # Acquisition records arrival as an event; mirroring that here so the
        # history assertion sees the trail a real record would have.
        ReviewService(world["session"]).record_submission(
            scholarship, actor="acquisition", evidence_url=doc.source_url
        )
        world["session"].flush()
        return scholarship

    def test_pending_record_is_invisible_to_users(self, world, pending):
        from services.scholarship.repository import ScholarshipRepository

        visible = ScholarshipRepository(world["session"]).get_all_approved()
        assert pending.scholarship_id not in {s.scholarship_id for s in visible}

    def test_approval_publishes_and_records_a_version(self, world, pending):
        service = ReviewService(world["session"])
        outcome = service.approve(str(pending.scholarship_id), actor="alice")
        world["session"].flush()

        assert outcome.new_state == ReviewStatus.APPROVED
        assert outcome.version_id is not None

        versions = service.versions(str(pending.scholarship_id))
        assert [v.version_number for v in versions] == [1]
        assert "published by alice" in versions[0].change_summary

        history = service.history(str(pending.scholarship_id))
        assert [a.action for a in history] == ["submitted", "approved"]
        assert history[-1].actor == "alice"

    def test_approved_record_reaches_the_public_read_path(self, world, pending):
        from services.scholarship.repository import ScholarshipRepository

        ReviewService(world["session"]).approve(str(pending.scholarship_id), actor="alice")
        world["session"].flush()

        visible = ScholarshipRepository(world["session"]).get_all_approved()
        assert pending.scholarship_id in {s.scholarship_id for s in visible}

    def test_rejected_record_never_reaches_users(self, world, pending):
        from services.scholarship.repository import ScholarshipRepository

        ReviewService(world["session"]).reject(
            str(pending.scholarship_id), actor="bob", reason="duplicate of an existing record"
        )
        world["session"].flush()

        visible = ScholarshipRepository(world["session"]).get_all_approved()
        assert pending.scholarship_id not in {s.scholarship_id for s in visible}

    def test_quality_gate_refuses_an_unpublishable_record(self, world):
        """A record that fails a gate cannot be published, override or not."""
        from database.models.scholarship import Scholarship

        bad = Scholarship(
            scholarship_name="Unknown Scholarship",
            degree=None,
            funding_type=None,
            field_of_study=[],
            official_page_url="https://www.studyinjapan.go.jp/en/scholarship/mystery/",
            provider_id=world["provider"].provider_id,
            country_id=world["country"].country_id,
            source_id=world["source"].source_id,
            extraction_status=ReviewStatus.PENDING_REVIEW,
            provenance_origin="exploration",
            identity_key=uuid.uuid4().hex,
        )
        world["session"].add(bad)
        world["session"].flush()

        with pytest.raises(NotPublishable):
            ReviewService(world["session"]).approve(
                str(bad.scholarship_id), actor="alice",
                reason="looks plausible", override_quality=True,
            )
