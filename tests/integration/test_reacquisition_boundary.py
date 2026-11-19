"""Regression tests: reacquisition must never mutate published data.

M9.1 Phase 2. The defect this file exists to prevent was reproduced against the
live Singapore record before any of this code changed: re-acquiring an APPROVED
scholarship wrote the freshly parsed deadline onto the row
(``None -> 2099-01-01``), bumped ``scholarship_version`` (8 -> 9), and left
``extraction_status = 'approved'`` and the review history untouched. Published
data moved with no state transition and nothing a reviewer could refuse.

Every test here runs against ``rollback_session``, so rows land in a
transaction that is always discarded and the shared development database is
never modified.

The shape of the guarantee:

    APPROVED ──reacquisition──► nothing changes on the row
                     │
                     └──► pending candidate revision (reviewable, not public)
                              │
                     ┌────────┴────────┐
                  reject              approve
                     │                   │
              scholarship           one version + one review action
              untouched             scholarship stays APPROVED
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.scholarship_candidate_revision import (
    CandidateStatus,
    ScholarshipCandidateRevision,
)
from database.models.scholarship_review_action import (
    ReviewActionType,
    ScholarshipReviewAction,
)
from database.models.scholarship_version import ScholarshipVersion
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_service import AcquisitionService
from services.review import (
    InvalidTransition,
    ReviewService,
    ReviewStatus,
    StaleCandidate,
)
from services.review.publication import is_published


@pytest.fixture
def session(rollback_session):
    return rollback_session


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


@pytest.fixture
def provider_and_source(session, jp_country):
    provider = Provider(
        provider_code="REACQ_TEST_PROV",
        provider_name="Reacquisition Boundary Foundation",
        provider_type="Foundation",
        country_id=jp_country.country_id,
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="Reacquisition Boundary Source",
        country_id=jp_country.country_id,
        provider_id=provider.provider_id,
        official_url="https://reacq-boundary.ac.uk/scholarship",
        crawl_entry_url="https://reacq-boundary.ac.uk/",
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
        source_url="https://reacq-boundary.ac.uk/scholarship",
        content_type="text/html",
        raw_content=content,
        checksum=hashlib.sha256(seed.encode()).hexdigest(),
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(doc)
    session.flush()
    return doc


def _fresh_extraction(source, *, deadline=None, cycle=None, degree=None):
    """A transient Scholarship shaped like a re-discovery's extraction.

    Built by hand rather than through the pipeline: these tests care about what
    acquisition does with an observation, not about extraction itself, and a
    hand-built object makes the "the published row was not touched" assertions
    unambiguous.
    """
    from database.models.scholarship import Scholarship
    from database.models.scholarship_timeline import ScholarshipTimeline

    fresh = Scholarship(
        scholarship_name="Reacquisition Boundary Scholarship",
        degree=degree,
        funding_type=None,
        field_of_study=[],
        application_url="https://reacq-boundary.ac.uk/apply",
        official_page_url="https://reacq-boundary.ac.uk/scholarship",
        provider_id=source.provider_id,
        country_id=source.country_id,
        source_id=source.source_id,
        extraction_status=ReviewStatus.PENDING_REVIEW,
    )
    if deadline is not None or cycle is not None:
        fresh.timeline = ScholarshipTimeline(
            application_deadline=deadline, application_cycle=cycle
        )
    return fresh


def _publish(session, provider, source, *, deadline=None, cycle=None):
    """Create a record and take it through review to APPROVED.

    Built through ReviewService rather than by assigning
    ``extraction_status = 'approved'``, because assigning that column directly
    is precisely the shortcut Phase 8 removes — and a fixture that took it
    would stop representing a genuinely reviewed record.
    """
    service = AcquisitionService(session)
    doc = _document(session, source, f"publish-{deadline}-{cycle}")
    # The pipeline speaks ISO strings; the ORM stores dates.
    iso_deadline = deadline.isoformat() if isinstance(deadline, date) else deadline
    saved = service._persist_with_dedup(
        _result(str(doc.document_id), iso_deadline, cycle), str(doc.document_id)
    )
    assert saved is not None, "fixture failed to persist the scholarship"

    review = ReviewService(session)
    review.approve(
        str(saved.scholarship_id),
        actor="reviewer-setup",
        reason="initial publication",
    )
    session.flush()
    session.refresh(saved)
    return saved


def _result(document_id: str, deadline, cycle=None, degree="Master"):
    from services.ingestion.extractor import (
        ExtractedDocument,
        ExtractedScholarship,
        Timeline,
    )
    from services.ingestion.orchestrator import PipelineResult
    from services.ingestion.validator import ValidationReport

    extracted = ExtractedScholarship(
        scholarship_name="Reacquisition Boundary Scholarship",
        provider_name="Reacquisition Boundary Foundation",
        country=None,
        degree=degree,
        field_of_study=["Computer Science"],
        application_url="https://reacq-boundary.ac.uk/apply",
        official_source="https://reacq-boundary.ac.uk/scholarship",
        timeline=Timeline(application_deadline=deadline, application_cycle=cycle),
    )
    return PipelineResult(
        document_id=document_id,
        source_url="https://reacq-boundary.ac.uk/scholarship",
        is_valid=True,
        extracted_data=extracted.model_dump(),
        validation_report=ValidationReport(is_valid=True, issues=[]),
        raw_extraction=ExtractedDocument(
            document_id=document_id,
            source_url="https://reacq-boundary.ac.uk/scholarship",
            scholarship=extracted,
        ),
    )


def _versions(session, sid):
    return (
        session.query(ScholarshipVersion)
        .filter(ScholarshipVersion.scholarship_id == sid)
        .order_by(ScholarshipVersion.version_number)
        .all()
    )


def _actions(session, sid):
    return (
        session.query(ScholarshipReviewAction)
        .filter(ScholarshipReviewAction.scholarship_id == sid)
        .all()
    )


def _reacquire(session, existing, fresh, source, document_id=None):
    return AcquisitionService(session)._merge_reacquisition(
        existing, fresh, "reacquisition probe page text", document_id=document_id
    )


class TestApprovedReacquisitionDoesNotMutate:
    """Requirement 1: approved + reacquisition must not mutate published fields."""

    def test_published_fields_unchanged(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source)
        sid = published.scholarship_id

        before_deadline = published.timeline.application_deadline if published.timeline else None
        before_state = published.deadline_state
        before_verified = published.last_verified_at
        before_versions = len(_versions(session, sid))

        future = date.today() + timedelta(days=200)
        fresh = _fresh_extraction(source, deadline=future, cycle="2028-cycle")
        _reacquire(session, published, fresh, source)
        session.flush()
        session.refresh(published)

        assert published.timeline.application_deadline == before_deadline
        assert published.deadline_state == before_state
        assert published.last_verified_at == before_verified
        assert published.extraction_status == ReviewStatus.APPROVED
        assert len(_versions(session, sid)) == before_versions, (
            "a proposal must not bump the published version history"
        )

    def test_deadline_state_not_recomputed(self, session, provider_and_source):
        """deadline_state gates public visibility, so it is published data too."""
        provider, source = provider_and_source
        published = _publish(
            session, provider, source, deadline=(date.today() - timedelta(days=10))
        )
        assert published.deadline_state == "expired"

        fresh = _fresh_extraction(
            source, deadline=date.today() + timedelta(days=300), cycle="new"
        )
        _reacquire(session, published, fresh, source)
        session.flush()
        session.refresh(published)

        assert published.deadline_state == "expired"

    def test_degree_not_overwritten(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source)
        published.degree = "Master"
        session.flush()

        fresh = _fresh_extraction(source, deadline=None, cycle=None, degree="PhD")
        _reacquire(session, published, fresh, source)
        session.flush()
        session.refresh(published)

        assert published.degree == "Master"

    def test_record_remains_published_and_visible(self, session, provider_and_source):
        """Requirements 2 and 5: visible to the public API, previous values intact."""
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        sid = published.scholarship_id

        fresh = _fresh_extraction(source, deadline=date(2029, 9, 9), cycle="2030")
        _reacquire(session, published, fresh, source)
        session.flush()

        from services.scholarship.repository import ScholarshipRepository

        repo = ScholarshipRepository(session)
        assert sid in [s.scholarship_id for s in repo.get_all_approved()]
        found, total = repo.search_approved("Reacquisition")
        assert sid in [s.scholarship_id for s in found]

        reloaded = repo.get_by_id(str(sid))
        assert reloaded.timeline.application_deadline == date(2027, 3, 1)
        assert is_published(reloaded)

    def test_matching_still_sees_published_value(self, session, provider_and_source):
        """Requirement: matching reads the published value, not the proposal."""
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))

        fresh = _fresh_extraction(source, deadline=date(2029, 9, 9), cycle="2030")
        _reacquire(session, published, fresh, source)
        session.flush()

        from services.scholarship.repository import ScholarshipRepository

        reloaded = ScholarshipRepository(session).get_by_id(str(published.scholarship_id))
        assert reloaded.timeline.application_deadline == date(2027, 3, 1)


class TestNonApprovedReacquisitionUnchanged:
    """Requirement 2: pending records keep the original acquisition behaviour."""

    def test_pending_record_still_merges_in_place(self, session, provider_and_source):
        provider, source = provider_and_source
        service = AcquisitionService(session)

        old = (date.today() - timedelta(days=30)).isoformat()
        new = (date.today() + timedelta(days=120)).isoformat()
        doc1 = _document(session, source, "pending-old")
        first = service._persist_with_dedup(_result(str(doc1.document_id), old, "2026"), str(doc1.document_id))
        assert first is not None
        assert first.extraction_status == ReviewStatus.PENDING_REVIEW

        doc2 = _document(session, source, "pending-new")
        second = service._persist_with_dedup(
            _result(str(doc2.document_id), new, "2027"), str(doc2.document_id)
        )

        assert second is None  # no duplicate row
        session.refresh(first)
        assert first.timeline.application_cycle == "2027"
        assert first.deadline_state == "active"

    def test_pending_merge_still_writes_a_version(self, session, provider_and_source):
        provider, source = provider_and_source
        service = AcquisitionService(session)

        doc1 = _document(session, source, "pending-v1")
        first = service._persist_with_dedup(
            _result(str(doc1.document_id), None, None), str(doc1.document_id)
        )
        doc2 = _document(session, source, "pending-v2")
        service._persist_with_dedup(
            _result(str(doc2.document_id), "2027-03-01", "2027"), str(doc2.document_id)
        )
        session.flush()

        versions = _versions(session, first.scholarship_id)
        assert len(versions) == 1
        assert "reacquired" in versions[0].change_summary


class TestRejectedReacquisition:
    """Requirement 3: a rejected record is not published, so it may still merge."""

    def test_rejected_record_merges_without_publication(self, session, provider_and_source):
        provider, source = provider_and_source
        rejected = _publish(session, provider, source, cycle="2026")
        ReviewService(session).reject(
            str(rejected.scholarship_id), actor="reviewer-setup", reason="not real"
        )
        session.flush()
        session.refresh(rejected)
        assert rejected.extraction_status == ReviewStatus.REJECTED

        future = date.today() + timedelta(days=90)
        doc = _document(session, source, "rejected-reacq")
        fresh = _fresh_extraction(source, deadline=future, cycle="2027")

        # Rejected rows are not public, so the acquisition path still folds the
        # fresh cycle in; no candidate is created because nothing is published.
        result = _reacquire(session, rejected, fresh, source, str(doc.document_id))
        session.flush()
        session.refresh(rejected)

        assert result is None
        assert rejected.timeline.application_cycle == "2027"
        assert rejected.extraction_status == ReviewStatus.REJECTED
        assert (
            session.query(ScholarshipCandidateRevision)
            .filter(ScholarshipCandidateRevision.scholarship_id == rejected.scholarship_id)
            .count()
            == 0
        )


class TestCandidateIsReviewable:
    """Requirement 4: fresh information must remain available for review."""

    def test_reacquisition_creates_pending_candidate(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1), cycle="2027")
        doc = _document(session, source, "candidate-doc")

        fresh = _fresh_extraction(
            source, deadline=date(2029, 9, 9), cycle="2029-cycle"
        )
        candidate = _reacquire(
            session, published, fresh, source, str(doc.document_id)
        )
        session.flush()

        assert candidate is not None
        assert candidate.status == CandidateStatus.PENDING
        assert candidate.origin == "reacquisition"
        assert candidate.source_url == "https://reacq-boundary.ac.uk/scholarship"
        assert str(candidate.raw_document_id) == str(doc.document_id)

        proposed = {c["field"]: c for c in candidate.proposed_changes}
        assert proposed["application_deadline"]["previous"] == "2027-03-01"
        assert proposed["application_deadline"]["new"] == "2029-09-09"
        assert proposed["application_cycle"]["previous"] == "2027"
        assert proposed["application_cycle"]["new"] == "2029-cycle"

    def test_candidate_carries_field_level_provenance(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        doc = _document(session, source, "candidate-prov-doc")

        fresh = _fresh_extraction(source, deadline=date(2029, 9, 9), cycle="2029")
        candidate = _reacquire(
            session, published, fresh, source, str(doc.document_id)
        )
        session.flush()

        prov = candidate.field_provenance["application_deadline"]
        assert prov["origin"] == "reacquisition"
        assert prov["document_id"] == str(doc.document_id)
        assert prov["source_url"] == "https://reacq-boundary.ac.uk/scholarship"
        assert prov["detected_at"]

    def test_candidate_visible_in_review_packet(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        fresh = _fresh_extraction(source, deadline=date(2029, 9, 9), cycle="2029")
        _reacquire(session, published, fresh, source)
        session.flush()

        packet = ReviewService(session).review_packet(str(published.scholarship_id))
        assert len(packet["pending_candidates"]) == 1
        assert packet["pending_candidates"][0]["status"] == CandidateStatus.PENDING
        # The packet's published view must still show the approved value.
        assert packet["timeline"]["application_deadline"] == date(2027, 3, 1)

    def test_unchanged_reacquisition_proposes_nothing(self, session, provider_and_source):
        """A re-crawl of an unchanged page is healthy, not a failure."""
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1), cycle="2027")

        fresh = _fresh_extraction(source, deadline=date(2027, 3, 1), cycle="2027")
        result = _reacquire(session, published, fresh, source)
        session.flush()

        assert result is None
        assert ReviewService(session).candidates(str(published.scholarship_id)) == []

    def test_repeat_reacquisition_supersedes_rather_than_duplicates(
        self, session, provider_and_source
    ):
        """A nightly crawl must not bury a reviewer in identical proposals."""
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))

        first = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2028, 1, 1)), source
        )
        second = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 1, 1)), source
        )
        session.flush()

        assert first.candidate_id == second.candidate_id
        pending = ReviewService(session).candidates(str(published.scholarship_id))
        assert len(pending) == 1
        assert pending[0].proposed_changes[0]["new"] == "2029-01-01"


class TestCandidateApproval:
    """Requirements 6, 7 and 8: approval publishes atomically and auditably."""

    def test_approval_publishes_new_value(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1), cycle="2027")
        doc = _document(session, source, "approve-doc")
        candidate = _reacquire(
            session,
            published,
            _fresh_extraction(source, deadline=date(2029, 9, 9), cycle="2029-cycle"),
            source,
            str(doc.document_id),
        )
        session.flush()

        outcome = ReviewService(session).approve_candidate(
            str(candidate.candidate_id),
            actor="reviewer-1",
            reason="official page confirms the 2029 cycle",
            evidence_url="https://reacq-boundary.ac.uk/scholarship",
        )
        session.flush()
        session.refresh(published)

        assert outcome.new_state == ReviewStatus.APPROVED
        assert published.extraction_status == ReviewStatus.APPROVED, (
            "approving a candidate must not move the record out of publication"
        )
        assert published.timeline.application_deadline == date(2029, 9, 9)
        assert published.timeline.application_cycle == "2029-cycle"

    def test_approval_creates_exactly_one_version(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        candidate = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        before = len(_versions(session, published.scholarship_id))
        ReviewService(session).approve_candidate(
            str(candidate.candidate_id), actor="reviewer-1", reason="verified"
        )
        session.flush()

        versions = _versions(session, published.scholarship_id)
        assert len(versions) == before + 1
        assert str(candidate.candidate_id) in versions[-1].change_summary

    def test_approval_creates_audit_action_linked_to_candidate(
        self, session, provider_and_source
    ):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        candidate = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        ReviewService(session).approve_candidate(
            str(candidate.candidate_id), actor="reviewer-1", reason="verified"
        )
        session.flush()

        actions = [
            a for a in _actions(session, published.scholarship_id)
            if a.action == ReviewActionType.CANDIDATE_APPROVED
        ]
        assert len(actions) == 1
        assert str(actions[0].candidate_id) == str(candidate.candidate_id)
        assert actions[0].actor == "reviewer-1"
        assert actions[0].version_id is not None
        assert actions[0].previous_state == actions[0].new_state == ReviewStatus.APPROVED

    def test_provenance_points_at_new_document_after_approval(
        self, session, provider_and_source
    ):
        """Requirement 7: the published value must cite the evidence used."""
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        published.field_provenance = {
            "application_deadline": {
                "origin": "machine_extraction",
                "source_url": "https://reacq-boundary.ac.uk/scholarship",
                "document_id": "original-document",
            }
        }
        session.flush()

        doc = _document(session, source, "prov-new-doc")
        candidate = _reacquire(
            session,
            published,
            _fresh_extraction(source, deadline=date(2029, 9, 9)),
            source,
            str(doc.document_id),
        )
        session.flush()
        ReviewService(session).approve_candidate(
            str(candidate.candidate_id), actor="reviewer-1", reason="verified"
        )
        session.flush()
        session.refresh(published)

        prov = published.field_provenance["application_deadline"]
        assert prov["origin"] == "human_review"
        assert prov["actor"] == "reviewer-1"
        assert prov["document_id"] == str(doc.document_id)
        # The machine-extracted provenance is preserved, not destroyed.
        assert prov["previous"]["origin"] == "machine_extraction"
        assert prov["previous"]["document_id"] == "original-document"

    def test_deadline_state_recomputed_on_approval(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(
            session, provider, source, deadline=(date.today() - timedelta(days=5))
        )
        assert published.deadline_state == "expired"

        candidate = _reacquire(
            session,
            published,
            _fresh_extraction(source, deadline=date.today() + timedelta(days=200)),
            source,
        )
        session.flush()
        # Still expired while pending: the proposal is not published.
        assert published.deadline_state == "expired"

        ReviewService(session).approve_candidate(
            str(candidate.candidate_id), actor="reviewer-1", reason="cycle reopened"
        )
        session.flush()
        session.refresh(published)

        assert published.deadline_state == "active"

    def test_candidate_cannot_be_approved_twice(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        candidate = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        review = ReviewService(session)
        review.approve_candidate(
            str(candidate.candidate_id), actor="reviewer-1", reason="verified"
        )
        session.flush()
        versions_after_first = len(_versions(session, published.scholarship_id))

        with pytest.raises(InvalidTransition):
            review.approve_candidate(
                str(candidate.candidate_id), actor="reviewer-2", reason="again"
            )

        assert len(_versions(session, published.scholarship_id)) == versions_after_first

    def test_approval_requires_a_reason(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        candidate = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        with pytest.raises(InvalidTransition):
            ReviewService(session).approve_candidate(
                str(candidate.candidate_id), actor="reviewer-1", reason=""
            )
        session.flush()
        session.refresh(published)
        assert published.timeline.application_deadline == date(2027, 3, 1)


class TestCandidateRejection:
    """Requirement 4: rejecting a candidate leaves the published record alone."""

    def test_rejection_leaves_scholarship_untouched(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1), cycle="2027")
        candidate = _reacquire(
            session,
            published,
            _fresh_extraction(source, deadline=date(2029, 9, 9), cycle="2029"),
            source,
        )
        session.flush()
        before_versions = len(_versions(session, published.scholarship_id))

        outcome = ReviewService(session).reject_candidate(
            str(candidate.candidate_id),
            actor="reviewer-1",
            reason="page reflects a different programme",
        )
        session.flush()
        session.refresh(published)
        session.refresh(candidate)

        assert outcome.new_state == ReviewStatus.APPROVED
        assert published.extraction_status == ReviewStatus.APPROVED
        assert published.timeline.application_deadline == date(2027, 3, 1)
        assert published.timeline.application_cycle == "2027"
        assert len(_versions(session, published.scholarship_id)) == before_versions
        assert candidate.status == CandidateStatus.REJECTED
        assert candidate.decided_by == "reviewer-1"

    def test_rejection_is_audited(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        candidate = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        ReviewService(session).reject_candidate(
            str(candidate.candidate_id),
            actor="reviewer-1",
            reason="stale mirror page",
        )
        session.flush()

        actions = [
            a for a in _actions(session, published.scholarship_id)
            if a.action == ReviewActionType.CANDIDATE_REJECTED
        ]
        assert len(actions) == 1
        assert actions[0].reason == "stale mirror page"
        assert actions[0].version_id is None

    def test_rejection_requires_a_reason(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        candidate = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        with pytest.raises(InvalidTransition):
            ReviewService(session).reject_candidate(
                str(candidate.candidate_id), actor="reviewer-1", reason="  "
            )

    def test_rejected_candidate_no_longer_actionable(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        candidate = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        review = ReviewService(session)
        review.reject_candidate(
            str(candidate.candidate_id), actor="reviewer-1", reason="no"
        )
        session.flush()

        assert review.candidates(str(published.scholarship_id)) == []
        with pytest.raises(InvalidTransition):
            review.approve_candidate(
                str(candidate.candidate_id), actor="reviewer-2", reason="changed mind"
            )


class TestStaleCandidateProtection:
    """Requirement 6: concurrent work must not silently overwrite each other."""

    def test_candidate_proposed_before_a_correction_cannot_be_approved(
        self, session, provider_and_source
    ):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        candidate = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        # A reviewer edits the record after the proposal was made.
        ReviewService(session).correct(
            str(published.scholarship_id),
            actor="reviewer-2",
            changes={"application_cycle": "2028-corrected"},
            reason="manual correction",
            requeue=False,
        )
        session.flush()

        with pytest.raises(StaleCandidate):
            ReviewService(session).approve_candidate(
                str(candidate.candidate_id), actor="reviewer-1", reason="verified"
            )

        session.refresh(published)
        # Neither value silently won.
        assert published.timeline.application_cycle == "2028-corrected"
        assert published.timeline.application_deadline == date(2027, 3, 1)

    def test_new_candidate_can_be_proposed_after_staleness(
        self, session, provider_and_source
    ):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        stale = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2029, 9, 9)), source
        )
        session.flush()

        ReviewService(session).correct(
            str(published.scholarship_id),
            actor="reviewer-2",
            changes={"application_cycle": "2028-corrected"},
            reason="manual correction",
            requeue=False,
        )
        session.flush()

        # The retry path: re-observe, then approve the refreshed proposal.
        fresh = _reacquire(
            session, published, _fresh_extraction(source, deadline=date(2030, 1, 1)), source
        )
        session.flush()
        assert fresh is not None
        # The same pending row is refreshed in place (one proposal per page),
        # and its base version is re-anchored to where the record is now, which
        # is what makes the retry approvable rather than permanently stale.
        assert fresh.candidate_id == stale.candidate_id
        assert fresh.base_version_number == ReviewService(
            session
        )._current_version_number(published.scholarship_id)

        ReviewService(session).approve_candidate(
            str(fresh.candidate_id), actor="reviewer-1", reason="re-verified"
        )
        session.flush()
        session.refresh(published)
        assert published.timeline.application_deadline == date(2030, 1, 1)


class TestProvenanceIntegrity:
    def test_provenance_is_not_fragmented_across_keys(self, session, provider_and_source):
        """The extractor keys the deadline as ``deadline``, the column as
        ``application_deadline``. Updating under the column name would leave a
        second, stale entry describing a value that is no longer published.
        """
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        published.field_provenance = {
            "deadline": {
                "origin": "deterministic_extractor",
                "source_url": "https://reacq-boundary.ac.uk/scholarship",
                "document_id": "original-document",
                "method": "deterministic_extractor",
            }
        }
        session.flush()

        candidate = _reacquire(
            session,
            published,
            _fresh_extraction(source, deadline=date(2029, 9, 9)),
            source,
        )
        session.flush()
        ReviewService(session).approve_candidate(
            str(candidate.candidate_id), actor="reviewer-1", reason="verified"
        )
        session.flush()
        session.refresh(published)

        provenance = published.field_provenance
        assert "application_deadline" not in provenance, (
            "the deadline must keep one provenance entry, not gain a second"
        )
        entry = provenance["deadline"]
        assert entry["origin"] == "human_review"
        assert entry["previous"]["method"] == "deterministic_extractor"


class TestCandidateFieldRestrictions:
    """Acquisition may not redefine identity, and cannot write arbitrary fields."""

    def test_identity_fields_are_not_proposable(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))

        candidate = ReviewService(session).propose_candidate(
            published,
            observed={
                "scholarship_name": "Completely Different Programme",
                "official_page_url": "https://evil.example.com/other",
                "application_url": "https://evil.example.com/apply",
                "degree": "PhD",
            },
            actor="acquisition",
        )
        session.flush()

        fields = {c["field"] for c in candidate.proposed_changes}
        assert fields == {"degree"}
        session.refresh(published)
        assert published.scholarship_name == "Reacquisition Boundary Scholarship"
        assert published.official_page_url == "https://reacq-boundary.ac.uk/scholarship"

    def test_unknown_fields_are_ignored_not_written(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))
        published.extraction_status = ReviewStatus.APPROVED

        candidate = ReviewService(session).propose_candidate(
            published,
            observed={
                "provider_id": "some-other-provider",
                "degree": "PhD",
                "country_id": "some-other-country",
            },
            actor="acquisition",
        )
        session.flush()

        assert {c["field"] for c in candidate.proposed_changes} == {"degree"}

    def test_no_observed_difference_creates_nothing(self, session, provider_and_source):
        provider, source = provider_and_source
        published = _publish(session, provider, source, deadline=date(2027, 3, 1))

        candidate = ReviewService(session).propose_candidate(
            published,
            observed={"application_deadline": date(2027, 3, 1)},
            actor="acquisition",
        )
        assert candidate is None
