"""Provenance must describe the value that is published *right now*.

M9.1 Phase 5. The defect this file exists to prevent: ``field_provenance`` was
written once, by the extraction pipeline, and never again. A reviewer could
correct a record all day and the provenance kept pointing at the machine
extraction — so the record claimed a machine produced a value a human chose.

The invariant under test:

    field_provenance[field] describes the evidence for the currently published
    value of that field, and superseded evidence stays recoverable.

    never:  published value = human-corrected
            provenance        = old machine extraction

    never:  published value = new reacquisition value
            provenance        = old document

Every test runs against ``rollback_session``, so rows land in a transaction
that is always discarded.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.scholarship import Scholarship
from database.models.scholarship_review_action import ScholarshipReviewAction
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.scholarship_version import ScholarshipVersion
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_service import AcquisitionService
from services.review import InvalidFieldValue, ReviewService, ReviewStatus
from services.review.publication import is_published
from services.review.service import _MAX_PREVIOUS_DEPTH


@pytest.fixture
def session(rollback_session):
    return rollback_session


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


@pytest.fixture
def provider_and_source(session, jp_country):
    provider = Provider(
        provider_code="PROV_TEST_PROV",
        provider_name="Provenance Test Foundation",
        provider_type="Foundation",
        country_id=jp_country.country_id,
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Provenance Test Source",
        country_id=jp_country.country_id,
        provider_id=provider.provider_id,
        official_url="https://prov-test.ac.uk/scholarship",
        crawl_entry_url="https://prov-test.ac.uk/",
        crawl_method="HTTP",
        crawl_frequency="monthly",
        status="Active",
    )
    session.add_all([provider, source])
    session.flush()
    return provider, source


def _document(session, source, seed: str, content: str = "scholarship page") -> RawDocument:
    doc = RawDocument(
        source_id=source.source_id,
        source_url="https://prov-test.ac.uk/scholarship",
        content_type="text/html",
        raw_content=content,
        checksum=hashlib.sha256(seed.encode()).hexdigest(),
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(doc)
    session.flush()
    return doc


def _result(document_id: str, *, degree="Master", funding_type=None):
    from services.ingestion.extractor import (
        ExtractedDocument,
        ExtractedScholarship,
        Timeline,
    )
    from services.ingestion.orchestrator import PipelineResult
    from services.ingestion.validator import ValidationReport

    extracted = ExtractedScholarship(
        scholarship_name="Provenance Test Scholarship",
        provider_name="Provenance Test Foundation",
        country=None,
        degree=degree,
        funding_type=funding_type,
        field_of_study=["Computer Science"],
        application_url="https://prov-test.ac.uk/apply",
        official_source="https://prov-test.ac.uk/scholarship",
        timeline=Timeline(application_deadline="2027-03-01"),
    )
    return PipelineResult(
        document_id=document_id,
        source_url="https://prov-test.ac.uk/scholarship",
        is_valid=True,
        extracted_data=extracted.model_dump(),
        validation_report=ValidationReport(is_valid=True, issues=[]),
        raw_extraction=ExtractedDocument(
            document_id=document_id,
            source_url="https://prov-test.ac.uk/scholarship",
            scholarship=extracted,
        ),
    )


def _publish(session, provider, source, *, degree="Master", funding_type=None, seed="base"):
    """Publish a record through the pipeline and review, never by assignment.

    ``extraction_status = 'approved'`` written directly would be exactly the
    shortcut this project is removing, and a fixture that took it would stop
    representing a genuinely reviewed record.
    """
    service = AcquisitionService(session)
    doc = _document(session, source, seed)
    saved = service._persist_with_dedup(
        _result(str(doc.document_id), degree=degree, funding_type=funding_type),
        str(doc.document_id),
    )
    assert saved is not None, "fixture failed to persist the scholarship"

    ReviewService(session).approve(
        str(saved.scholarship_id), actor="reviewer-setup", reason="initial publication"
    )
    session.flush()
    session.refresh(saved)
    return saved


def _prov(scholarship, field="degree"):
    return (scholarship.field_provenance or {}).get(field) or {}


def _actions(session, sid):
    return (
        session.query(ScholarshipReviewAction)
        .filter(ScholarshipReviewAction.scholarship_id == sid)
        .order_by(ScholarshipReviewAction.occurred_at)
        .all()
    )


def _versions(session, sid):
    return (
        session.query(ScholarshipVersion)
        .filter(ScholarshipVersion.scholarship_id == sid)
        .order_by(ScholarshipVersion.version_number)
        .all()
    )


def _correct(session, scholarship, **kwargs):
    """Run one correction and return the refreshed provenance for the field."""
    outcome = ReviewService(session).correct(
        str(scholarship.scholarship_id),
        actor=kwargs.pop("actor", "reviewer-a"),
        reason=kwargs.pop("reason", "corrected from the official page"),
        requeue=kwargs.pop("requeue", False),
        **kwargs,
    )
    session.flush()
    session.refresh(scholarship)
    return outcome


class TestNormalExtractionProvenance:
    """A: extraction produces a current value and machine provenance."""

    def test_extraction_writes_machine_provenance(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source)

        prov = _prov(published)
        assert prov["origin"] == "machine_extracted"
        assert prov["method"]
        assert prov["document_id"]
        assert prov["source_url"] == published.official_page_url
        # Machine provenance names no reviewer: nobody has looked at this yet.
        assert "actor" not in prov
        assert "corrected_at" not in prov


class TestReviewerCorrectionProvenance:
    """B: a plain reviewer correction produces human provenance."""

    def test_correction_rewrites_provenance_to_human(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source)
        machine = dict(_prov(published))

        _correct(
            session,
            published,
            changes={"degree": "Bachelor"},
            actor="reviewer-a",
            reason="official page states Bachelor's, not Master's",
        )

        prov = _prov(published)
        assert published.degree == "Bachelor"
        assert prov["origin"] == "human_review"
        assert prov["actor"] == "reviewer-a"
        assert prov["reason"] == "official page states Bachelor's, not Master's"
        assert prov["corrected_at"]
        assert prov["current_value"] == "Bachelor"
        assert prov["previous_value"] == "Master"

        # The machine evidence is preserved, not destroyed.
        assert prov["previous"]["origin"] == "machine_extracted"
        assert prov["previous"]["document_id"] == machine["document_id"]

    def test_correction_answers_all_six_questions(self, session, provider_and_source):
        """What / who / why / evidence / when / what came before."""
        provider, source = provider_and_source
        published = _publish(session, provider, source)

        _correct(
            session,
            published,
            changes={"degree": "PhD"},
            actor="reviewer-b",
            reason="source updated after publication",
            evidence_url="https://prov-test.ac.uk/scholarship?rev=2",
        )

        prov = _prov(published)
        assert prov["current_value"] == "PhD"  # what
        assert prov["actor"] == "reviewer-b"  # who
        assert prov["reason"].startswith("source updated")  # why
        assert prov["evidence_url"].endswith("?rev=2")  # evidence
        assert prov["corrected_at"]  # when
        assert prov["previous"]["origin"] == "machine_extracted"  # what came before

    def test_correction_is_audited_and_versioned(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source)
        sid = published.scholarship_id

        outcome = _correct(session, published, changes={"degree": "Bachelor"})

        actions = _actions(session, sid)
        assert actions[-1].action == "corrected"
        assert actions[-1].actor == "reviewer-a"
        assert str(actions[-1].version_id) == outcome.version_id
        assert [c["field"] for c in actions[-1].field_changes] == ["degree"]

        versions = _versions(session, sid)
        assert str(versions[-1].version_id) == outcome.version_id


class TestEvidenceHandling:
    """C and D: evidence is recorded when given, and never invented."""

    def test_evidence_url_is_reflected_in_current_provenance(
        self, session, provider_and_source
    ):
        provider, source = provider_and_source
        published = _publish(session, provider, source)

        _correct(
            session,
            published,
            changes={"degree": "Bachelor"},
            evidence_url="https://prov-test.ac.uk/archive/degree",
        )

        prov = _prov(published)
        assert prov["evidence_url"] == "https://prov-test.ac.uk/archive/degree"
        assert prov["source_url"] == "https://prov-test.ac.uk/archive/degree"

    def test_no_evidence_url_creates_no_evidence(self, session, provider_and_source):
        """A missing evidence URL is recorded as null, never backfilled."""
        provider, source = provider_and_source
        published = _publish(session, provider, source)
        machine_document = _prov(published)["document_id"]

        _correct(session, published, changes={"degree": "Bachelor"})

        prov = _prov(published)
        assert prov["evidence_url"] is None
        # No invented document: the old one backs the *previous* value only.
        assert prov["document_id"] is None
        assert prov["previous"]["document_id"] == machine_document


class TestCandidateApprovalProvenance:
    """E: the Phase 2 approval path still points at the accepted evidence."""

    def test_approval_keeps_human_origin_and_new_document(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source)
        published.field_provenance = {
            "degree": {
                "origin": "machine_extraction",
                "source_url": published.official_page_url,
                "document_id": "original-document",
            }
        }
        session.flush()

        from services.exploration.acquisition_service import AcquisitionService as _AS

        doc = _document(session, source, "candidate-doc")
        fresh = Scholarship(
            scholarship_name="Provenance Test Scholarship",
            degree="Bachelor",
            field_of_study=["Computer Science"],
            application_url="https://prov-test.ac.uk/apply",
            official_page_url="https://prov-test.ac.uk/scholarship",
            provider_id=source.provider_id,
            country_id=source.country_id,
            source_id=source.source_id,
            extraction_status=ReviewStatus.PENDING_REVIEW,
            timeline=ScholarshipTimeline(application_deadline=date(2027, 3, 1)),
        )
        candidate = _AS(session)._merge_reacquisition(
            published, fresh, "page text", document_id=str(doc.document_id)
        )
        session.flush()

        ReviewService(session).approve_candidate(
            str(candidate.candidate_id), actor="reviewer-1", reason="verified"
        )
        session.flush()
        session.refresh(published)

        prov = _prov(published)
        assert published.degree == "Bachelor"
        assert prov["origin"] == "human_review"
        assert prov["document_id"] == str(doc.document_id)
        assert prov["previous"]["document_id"] == "original-document"


class TestMultipleCorrections:
    """F: machine -> human A -> human B, with B current and history intact."""

    def test_latest_correction_is_current_and_earlier_ones_recoverable(
        self, session, provider_and_source
    ):
        provider, source = provider_and_source
        published = _publish(session, provider, source)

        _correct(
            session, published, changes={"degree": "Bachelor"}, actor="reviewer-a"
        )
        _correct(
            session, published, changes={"degree": "Master"}, actor="reviewer-b"
        )

        prov = _prov(published)
        assert published.degree == "Master"
        assert prov["origin"] == "human_review"
        assert prov["actor"] == "reviewer-b"
        assert prov["current_value"] == "Master"

        human_a = prov["previous"]
        assert human_a["actor"] == "reviewer-a"
        assert human_a["current_value"] == "Bachelor"

        machine = human_a["previous"]
        assert machine["origin"] == "machine_extracted"
        assert machine["document_id"]

        # The audit trail keeps every value regardless of nesting depth.
        sid = published.scholarship_id
        assert len(_versions(session, sid)) >= 3
        degree_changes = [
            c
            for action in _actions(session, sid)
            for c in (action.field_changes or [])
            if c.get("field") == "degree"
        ]
        assert [c["new"] for c in degree_changes] == ["Bachelor", "Master"]

    def test_provenance_history_is_bounded(self, session, provider_and_source):
        """Repeated corrections cannot grow an unbounded JSON blob per field."""
        provider, source = provider_and_source
        published = _publish(session, provider, source)

        values = ["Bachelor", "PhD", "Master", "Bachelor", "PhD", "Master", "Bachelor"]
        for value in values:
            _correct(session, published, changes={"degree": value}, actor="reviewer-loop")

        prov = _prov(published)
        depth = 0
        node = prov
        while isinstance(node.get("previous"), dict):
            depth += 1
            node = node["previous"]
        # The current entry plus the bounded chain it preserves.
        assert depth <= _MAX_PREVIOUS_DEPTH + 1
        assert node.get("truncated") is True


class TestReacquisitionAfterCorrection:
    """G: a fresh source must not revert a human correction to machine evidence."""

    def test_pending_reacquisition_leaves_human_provenance_alone(
        self, session, provider_and_source
    ):
        provider, source = provider_and_source
        published = _publish(session, provider, source, funding_type="Partial Funded")
        _correct(
            session,
            published,
            changes={"funding_type": "Fully Funded"},
            actor="reviewer-a",
            reason="source says the award covers all tuition",
        )

        fresh = Scholarship(
            scholarship_name="Provenance Test Scholarship",
            degree="Master",
            funding_type="Partial Funded",
            field_of_study=["Computer Science"],
            application_url="https://prov-test.ac.uk/apply",
            official_page_url="https://prov-test.ac.uk/scholarship",
            provider_id=source.provider_id,
            country_id=source.country_id,
            source_id=source.source_id,
            extraction_status=ReviewStatus.PENDING_REVIEW,
            timeline=ScholarshipTimeline(application_deadline=date(2027, 3, 1)),
        )
        doc = _document(session, source, "reacq-after-correction")
        AcquisitionService(session)._merge_reacquisition(
            published, fresh, "page text", document_id=str(doc.document_id)
        )
        session.flush()
        session.refresh(published)

        # Nothing was published, and the human correction is still described as
        # the human's work — not as something the extractor produced.
        assert published.funding_type == "Fully Funded"
        prov = _prov(published, "funding_type")
        assert prov["origin"] == "human_review"
        assert prov["actor"] == "reviewer-a"
        assert prov["document_id"] is None

    def test_approved_reacquisition_points_at_the_new_document(
        self, session, provider_and_source
    ):
        provider, source = provider_and_source
        published = _publish(session, provider, source, funding_type="Partial Funded")
        _correct(
            session,
            published,
            changes={"funding_type": "Fully Funded"},
            actor="reviewer-a",
            reason="source says the award covers all tuition",
        )

        fresh = Scholarship(
            scholarship_name="Provenance Test Scholarship",
            degree="Master",
            funding_type="Partial Funded",
            field_of_study=["Computer Science"],
            application_url="https://prov-test.ac.uk/apply",
            official_page_url="https://prov-test.ac.uk/scholarship",
            provider_id=source.provider_id,
            country_id=source.country_id,
            source_id=source.source_id,
            extraction_status=ReviewStatus.PENDING_REVIEW,
            timeline=ScholarshipTimeline(application_deadline=date(2027, 3, 1)),
        )
        doc = _document(session, source, "reacq-approved")
        candidate = AcquisitionService(session)._merge_reacquisition(
            published, fresh, "page text", document_id=str(doc.document_id)
        )
        session.flush()

        ReviewService(session).approve_candidate(
            str(candidate.candidate_id), actor="reviewer-2", reason="upstream reverted"
        )
        session.flush()
        session.refresh(published)

        prov = _prov(published, "funding_type")
        assert published.funding_type == "Partial Funded"
        # New evidence, not the old document.
        assert prov["origin"] == "human_review"
        assert prov["document_id"] == str(doc.document_id)
        assert prov["previous"]["actor"] == "reviewer-a"


class TestUnmappedQualificationRemediation:
    """H: empty a controlled field with the source evidence attached."""

    def test_null_degree_records_the_source_wording(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, degree="Master")
        sid = published.scholarship_id
        versions_before = len(_versions(session, sid))

        _correct(
            session,
            published,
            changes={"degree": None},
            actor="reviewer-a",
            reason=(
                "source describes the qualification as a diploma; Polaris has no "
                "degree level for it"
            ),
            evidence_url="https://prov-test.ac.uk/scholarship",
            unmapped_qualification={"degree": "diploma"},
        )

        prov = _prov(published)
        assert published.degree is None
        assert prov["origin"] == "human_review"
        assert prov["current_value"] is None
        assert prov["previous_value"] == "Master"
        assert prov["unmapped_qualification"] == "diploma"
        assert prov["note"]

        # The invalid value a human retired is still visible in history.
        assert prov["previous"]["origin"] == "machine_extracted"
        assert len(_versions(session, sid)) == versions_before + 1
        degree_changes = [
            c
            for action in _actions(session, sid)
            for c in (action.field_changes or [])
            if c.get("field") == "degree"
        ]
        assert degree_changes[-1]["previous"] == "Master"
        assert degree_changes[-1]["new"] is None

        # Remediating the vocabulary violation keeps the record published.
        assert published.extraction_status == ReviewStatus.APPROVED
        assert is_published(published)

    def test_evidence_contradicting_the_value_is_refused(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, degree="Master")

        with pytest.raises(InvalidFieldValue):
            _correct(
                session,
                published,
                changes={"degree": "Bachelor"},
                reason="nonsense combination",
                unmapped_qualification={"degree": "diploma"},
            )

    def test_evidence_for_an_uncorrected_field_is_refused(
        self, session, provider_and_source
    ):
        provider, source = provider_and_source
        published = _publish(session, provider, source)

        with pytest.raises(InvalidFieldValue):
            _correct(
                session,
                published,
                changes={"degree": None},
                reason="no evidence for this field",
                unmapped_qualification={"funding_type": "grant"},
            )
