"""Integration tests: freshness integration in the acquisition path.

Covers: deadline_state assignment at persist, re-acquisition merging (new
cycle wins, no duplicate rows, version provenance appended), and the
query-time expired gate in the repository.
"""

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from database.models.country import Country
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_service import AcquisitionService
from services.ingestion.extractor import ExtractedDocument, ExtractedScholarship, Timeline
from services.ingestion.orchestrator import PipelineResult
from services.ingestion.validator import ValidationReport
from services.scholarship.repository import ScholarshipRepository


@pytest.fixture
def session(rollback_session):
    return rollback_session


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


@pytest.fixture
def provider_and_source(session, jp_country):
    provider = Provider(
        provider_code="FRESH_TEST_PROV",
        provider_name="Freshness Test Foundation",
        provider_type="Foundation",
        country_id=jp_country.country_id,
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Freshness Test Source",
        country_id=jp_country.country_id,
        provider_id=provider.provider_id,
        official_url="https://fresh-test.example.org/scholarship",
        crawl_entry_url="https://fresh-test.example.org/",
        crawl_method="HTTP",
        crawl_frequency="monthly",
        status="Active",
    )
    session.add_all([provider, source])
    session.flush()
    return provider, source


def _raw_document(session, source, seed: str, content: str = "scholarship page") -> RawDocument:
    doc = RawDocument(
        source_id=source.source_id,
        source_url="https://fresh-test.example.org/scholarship",
        content_type="text/html",
        raw_content=content,
        checksum=hashlib.sha256(seed.encode()).hexdigest(),
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(doc)
    session.flush()
    return doc


def _result(document_id: str, deadline: str | None, cycle: str | None = None) -> PipelineResult:
    extracted = ExtractedScholarship(
        scholarship_name="Freshness Test Scholarship",
        provider_name="Freshness Test Foundation",
        country=None,
        application_url="https://fresh-test.example.org/apply",
        official_source="https://fresh-test.example.org/scholarship",
        timeline=Timeline(application_deadline=deadline, application_cycle=cycle),
    )
    return PipelineResult(
        document_id=document_id,
        source_url="https://fresh-test.example.org/scholarship",
        is_valid=True,
        extracted_data=extracted.model_dump(),
        validation_report=ValidationReport(is_valid=True, issues=[]),
        raw_extraction=ExtractedDocument(
            document_id=document_id,
            source_url="https://fresh-test.example.org/scholarship",
            scholarship=extracted,
        ),
    )


def _persist(service, session, source, deadline, cycle=None, seed="s1", content="deadline: March 1, 2027"):
    doc = _raw_document(session, source, seed, content)
    return service._persist_with_dedup(
        _result(str(doc.document_id), deadline, cycle), str(doc.document_id)
    )

class TestDeadlineStateAtPersist:
    def test_future_deadline_marked_active(self, session, provider_and_source):
        _, source = provider_and_source
        service = AcquisitionService(session)
        future = (date.today() + timedelta(days=90)).isoformat()
        saved = _persist(service, session, source, future, seed="future-1")
        assert saved is not None
        assert saved.deadline_state == "active"

    def test_past_deadline_marked_expired(self, session, provider_and_source):
        _, source = provider_and_source
        service = AcquisitionService(session)
        past = (date.today() - timedelta(days=90)).isoformat()
        saved = _persist(service, session, source, past, seed="past-1")
        assert saved is not None
        assert saved.deadline_state == "expired"

    def test_missing_deadline_is_unknown_not_invented(self, session, provider_and_source):
        _, source = provider_and_source
        service = AcquisitionService(session)
        saved = _persist(service, session, source, None, seed="unknown-1")
        assert saved is not None
        assert saved.deadline_state == "unknown"

    def test_rolling_page_text_preserved_as_rolling(self, session, provider_and_source):
        _, source = provider_and_source
        service = AcquisitionService(session)
        past = (date.today() - timedelta(days=90)).isoformat()
        saved = _persist(
            service, session, source, past, seed="rolling-1",
            content="Applications accepted until all positions are filled",
        )
        assert saved.deadline_state == "rolling"


class TestReacquisitionMerge:
    def test_newer_cycle_wins_no_duplicate(self, session, provider_and_source):
        provider, source = provider_and_source
        service = AcquisitionService(session)
        old_deadline = (date.today() - timedelta(days=30)).isoformat()
        new_deadline = (date.today() + timedelta(days=120)).isoformat()

        first = _persist(service, session, source, old_deadline, cycle="2026", seed="c-old")
        second = _persist(service, session, source, new_deadline, cycle="2027", seed="c-new")

        assert first is not None
        assert second is None  # merged into canonical row, no duplicate
        scholarships = (
            session.query(Scholarship)
            .filter(Scholarship.provider_id == provider.provider_id)
            .all()
        )
        assert len(scholarships) == 1  # no duplicate row created
        scholarship = scholarships[0]
        assert scholarship.timeline.application_deadline.isoformat() == new_deadline
        assert scholarship.timeline.application_cycle == "2027"
        assert scholarship.deadline_state == "active"

    def test_reacquisition_appends_version_provenance(self, session, provider_and_source):
        from database.models.scholarship_version import ScholarshipVersion

        provider, source = provider_and_source
        service = AcquisitionService(session)
        _persist(service, session, source, None, seed="v-1")
        _persist(service, session, source, "2027-03-01", seed="v-2")

        # Scope to this test's own scholarship rows: the shared development
        # database legitimately holds versions from real acquisition runs, and
        # an unscoped count would count those too.
        scholarship_ids = select(Scholarship.scholarship_id).where(
            Scholarship.provider_id == provider.provider_id
        )
        versions = (
            session.query(ScholarshipVersion)
            .filter(ScholarshipVersion.scholarship_id.in_(scholarship_ids))
            .order_by(ScholarshipVersion.version_number)
            .all()
        )
        assert len(versions) == 1  # first persist created the row; second merged
        assert "reacquired" in (versions[0].change_summary or "")


class TestQueryTimeExpiredGate:
    def test_get_all_approved_excludes_expired(self, session, provider_and_source):
        _, source = provider_and_source
        service = AcquisitionService(session)
        past = (date.today() - timedelta(days=10)).isoformat()
        expired_row = _persist(service, session, source, past, seed="gate-1")
        expired_row.extraction_status = "approved"
        session.flush()

        approved = ScholarshipRepository(session).get_all_approved()
        ids = [s.scholarship_id for s in approved]
        assert expired_row.scholarship_id not in ids

    def test_unclassified_row_stays_visible(self, session, provider_and_source):
        _, source = provider_and_source
        service = AcquisitionService(session)
        row = _persist(service, session, source, None, seed="gate-2")
        row.extraction_status = "approved"
        row.deadline_state = None  # simulate legacy/unclassified row
        session.flush()

        approved = ScholarshipRepository(session).get_all_approved()
        assert row.scholarship_id in [s.scholarship_id for s in approved]

    def test_reclassify_sweep_moves_active_to_expired(self, session, provider_and_source):
        _, source = provider_and_source
        service = AcquisitionService(session)
        soon_past = (date.today() - timedelta(days=2)).isoformat()
        row = _persist(service, session, source, soon_past, seed="sweep-1")
        assert row.deadline_state == "expired"  # classified at persist
        row.deadline_state = "active"  # simulate a stale classification
        session.flush()

        changed = ScholarshipRepository(session).reclassify_deadline_states()
        assert changed >= 1
        session.refresh(row)
        assert row.deadline_state == "expired"
