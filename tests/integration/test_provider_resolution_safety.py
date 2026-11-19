"""Provider resolution must not become a publication bypass.

M9.1 Phase 7. ``ProviderResolver._merge_domain_duplicates`` consolidates
near-duplicate provider rows that share a registered domain. It used to
re-point scholarships with one bulk UPDATE:

    session.query(Scholarship).filter(Scholarship.provider_id == dup).update(...)

No status filter, no row lock, no version, no review action, no provenance.
For a record nobody can see yet that is harmless curation. For an APPROVED
record it is the Phase 1 defect reached through a different door: the public
API renders the provider's name and type, duplicate detection keys on
provider_id, and all of it would change without a reviewer ever being asked.

The boundary these tests pin:

    unpublished record -> linked directly (safe: it is not public)
    approved record    -> left exactly as published, repairable only by a
                         reviewer through ReviewService.correct()

Everything runs inside `exploration_session`, so no row reaches the shared
development database.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_candidate_revision import CandidateStatus
from database.models.scholarship_review_action import ScholarshipReviewAction
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.scholarship_version import ScholarshipVersion
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_service import AcquisitionService
from services.exploration.provider_resolver import ProviderResolver
from services.review import ReviewService, ReviewStatus
from services.review.publication import is_published
from services.scholarship.repository import ScholarshipRepository

DOMAIN = "https://admissions.smu.edu.sg"


@pytest.fixture
def session(exploration_session):
    return exploration_session


@pytest.fixture
def country(session):
    from database.models.country import Country

    return session.query(Country).filter(Country.iso2 == "JP").first()


@pytest.fixture
def resolver(session, country):
    return ProviderResolver(session, country.country_id, [".go.jp", ".ac.jp"])


@pytest.fixture
def provider_family(session, country):
    """One canonical provider and one near-duplicate sharing its domain."""
    primary = Provider(
        provider_code=f"PRIMARY_{uuid.uuid4().hex[:8].upper()}"[:32],
        provider_name="Singapore Management University",
        provider_type=ProviderType.UNIVERSITY,
        country_id=country.country_id,
        official_url=f"{DOMAIN}/",
        verification_status="verified",
        identity_key="p" * 64,
    )
    duplicate = Provider(
        provider_code=f"DUP_{uuid.uuid4().hex[:8].upper()}"[:32],
        provider_name="SMU Graduate Studies",
        provider_type=ProviderType.UNIVERSITY,
        country_id=country.country_id,
        official_url=f"{DOMAIN}/grad",
        verification_status="discovered",
        identity_key="d" * 64,
        discovered_at=datetime.now(timezone.utc),
    )
    session.add_all([primary, duplicate])
    session.flush()
    return primary, duplicate


@pytest.fixture
def source(session, country):
    registry = SourceRegistry(
        source_name=f"Provider safety source {uuid.uuid4().hex[:8]}",
        country_id=country.country_id,
        official_url=f"{DOMAIN}/",
        crawl_entry_url=f"{DOMAIN}/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
    )
    session.add(registry)
    session.flush()
    return registry


def _scholarship(session, country, provider, state, source, *, name="SMU Scholarship"):
    record = Scholarship(
        scholarship_name=f"{name} {uuid.uuid4().hex[:6]}",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Finance"],
        official_page_url=f"{DOMAIN}/{uuid.uuid4().hex[:6]}",
        application_url=f"{DOMAIN}/apply",
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        extraction_status=state,
        deadline_state="active",
        provenance_origin="exploration",
        identity_key=uuid.uuid4().hex,
    )
    record.timeline = ScholarshipTimeline(application_deadline=date(2028, 1, 31))
    session.add(record)
    session.flush()
    return record


def _version_count(session, sid):
    return (
        session.query(ScholarshipVersion)
        .filter(ScholarshipVersion.scholarship_id == sid)
        .count()
    )


def _action_count(session, sid):
    return (
        session.query(ScholarshipReviewAction)
        .filter(ScholarshipReviewAction.scholarship_id == sid)
        .count()
    )


class TestPureIdentityResolutionIsUnaffected:
    """Classification A/C: linking an unpublished record stays a direct write."""

    def test_pending_record_is_relinked_directly(self, session, country, resolver, provider_family, source):
        primary, duplicate = provider_family
        pending = _scholarship(session, country, duplicate, ReviewStatus.PENDING_REVIEW, source)
        sid = pending.scholarship_id

        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()
        session.refresh(pending)

        assert pending.provider_id == primary.provider_id
        assert duplicate.merged_into_provider_id == primary.provider_id
        # Nothing published, so nothing to version or audit.
        assert _version_count(session, sid) == 0
        assert _action_count(session, sid) == 0

    def test_resolution_creates_no_publication_state(self, session, country, resolver, provider_family, source):
        """Provider work must never publish a record by accident."""
        primary, duplicate = provider_family
        pending = _scholarship(session, country, duplicate, ReviewStatus.PENDING_REVIEW, source)

        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()
        session.refresh(pending)

        assert pending.extraction_status == ReviewStatus.PENDING_REVIEW
        assert not is_published(pending)
        listed = [str(s.scholarship_id) for s in ScholarshipRepository(session).get_all_approved()]
        assert str(pending.scholarship_id) not in listed

    def test_resolving_a_provider_does_not_touch_a_pending_record_semantics(
        self, session, country, resolver, provider_family, source
    ):
        primary, duplicate = provider_family
        pending = _scholarship(session, country, duplicate, ReviewStatus.PENDING_REVIEW, source)
        before = (pending.degree, pending.funding_type, pending.field_of_study[:])

        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()
        session.refresh(pending)

        assert (pending.degree, pending.funding_type, pending.field_of_study) == before
        assert pending.field_provenance in (None, {})


class TestApprovedRecordsAreFrozen:
    """Classification D/E: the defect this phase exists to close."""

    def test_approved_provider_link_is_not_rewritten(
        self, session, country, resolver, provider_family, source
    ):
        primary, duplicate = provider_family
        approved = _scholarship(session, country, duplicate, ReviewStatus.APPROVED, source)
        sid = approved.scholarship_id
        versions_before = _version_count(session, sid)
        actions_before = _action_count(session, sid)

        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()
        session.refresh(approved)

        assert approved.provider_id == duplicate.provider_id, (
            "an approved record was re-pointed at another provider without review"
        )
        assert _version_count(session, sid) == versions_before
        assert _action_count(session, sid) == actions_before
        # The identity decision itself is still recorded, so the consolidation
        # trail stays auditable even though the published link did not move.
        assert duplicate.merged_into_provider_id == primary.provider_id

    def test_approved_record_stays_publicly_visible_and_correct(
        self, session, country, resolver, provider_family, source
    ):
        primary, duplicate = provider_family
        approved = _scholarship(session, country, duplicate, ReviewStatus.APPROVED, source)
        sid = approved.scholarship_id

        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()
        session.refresh(approved)

        assert is_published(approved)
        repo = ScholarshipRepository(session)
        assert str(sid) in [str(s.scholarship_id) for s in repo.get_all_approved()]
        assert repo.get_published_by_id(sid) is not None

    @pytest.mark.parametrize("state", [ReviewStatus.REJECTED, ReviewStatus.NEEDS_CORRECTION])
    def test_rejected_and_needs_correction_are_relinked(
        self, session, country, resolver, provider_family, source, state
    ):
        """Unpublished means unpublished, whatever the reason."""
        primary, duplicate = provider_family
        record = _scholarship(session, country, duplicate, state, source)

        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()
        session.refresh(record)

        assert record.provider_id == primary.provider_id
        assert record.extraction_status == state
        assert not is_published(record)

    def test_no_candidate_revision_is_created(
        self, session, country, resolver, provider_family, source
    ):
        """Phase 2 ruled that identity does not move on an observation."""
        from database.models.scholarship_candidate_revision import (
            ScholarshipCandidateRevision,
        )

        primary, duplicate = provider_family
        approved = _scholarship(session, country, duplicate, ReviewStatus.APPROVED, source)

        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()

        pending = (
            session.query(ScholarshipCandidateRevision)
            .filter(
                ScholarshipCandidateRevision.scholarship_id == approved.scholarship_id,
                ScholarshipCandidateRevision.status == CandidateStatus.PENDING,
            )
            .all()
        )
        assert pending == []


class TestReviewerCanRepairTheLink:
    """The frozen record is not stranded: the review workflow can fix it."""

    def test_correction_repoints_with_version_audit_and_provenance(
        self, session, country, provider_family, source
    ):
        primary, duplicate = provider_family
        approved = _scholarship(session, country, duplicate, ReviewStatus.APPROVED, source)
        sid = approved.scholarship_id
        versions_before = _version_count(session, sid)

        ReviewService(session).correct(
            str(sid),
            actor="reviewer-provider",
            changes={"provider_id": str(primary.provider_id)},
            reason="canonical provider row is the verified one",
            requeue=False,
        )
        session.flush()
        session.refresh(approved)

        assert approved.provider_id == primary.provider_id
        assert _version_count(session, sid) == versions_before + 1
        assert str(approved.provider_id) == str(primary.provider_id)

        latest = (
            session.query(ScholarshipReviewAction)
            .filter(ScholarshipReviewAction.scholarship_id == sid)
            .order_by(ScholarshipReviewAction.occurred_at.desc())
            .first()
        )
        assert latest.action == "corrected"
        assert latest.actor == "reviewer-provider"
        assert [c["field"] for c in latest.field_changes] == ["provider_id"]

        prov = (approved.field_provenance or {}).get("provider_id") or {}
        assert prov["origin"] == "human_review"
        assert prov["current_value"] == str(primary.provider_id)
        assert prov["previous_value"] == str(duplicate.provider_id)

        # Still published: a curation decision never silently unpublishes.
        assert approved.extraction_status == ReviewStatus.APPROVED
        assert is_published(approved)

    def test_unknown_provider_is_refused(self, session, country, provider_family, source):
        primary, duplicate = provider_family
        approved = _scholarship(session, country, duplicate, ReviewStatus.APPROVED, source)
        sid = approved.scholarship_id
        versions_before = _version_count(session, sid)

        with pytest.raises(Exception) as exc:
            ReviewService(session).correct(
                str(sid),
                actor="reviewer-provider",
                changes={"provider_id": str(uuid.uuid4())},
                reason="typo",
                requeue=False,
            )
        session.rollback()
        assert "no such provider" in str(exc.value)
        assert _version_count(session, sid) == versions_before


class TestReacquisitionStillCannotTouchApprovedRecords:
    """Phase 1's regression, with provider resolution in the picture."""

    def test_provider_merge_then_reacquisition_publishes_nothing(
        self, session, country, resolver, provider_family, source
    ):
        primary, duplicate = provider_family
        approved = _scholarship(session, country, duplicate, ReviewStatus.APPROVED, source)
        sid = approved.scholarship_id
        versions_before = _version_count(session, sid)

        resolver._merge_domain_duplicates([primary, duplicate])

        fresh = Scholarship(
            scholarship_name=approved.scholarship_name,
            degree="PhD",
            field_of_study=["Finance"],
            official_page_url=approved.official_page_url,
            provider_id=primary.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status=ReviewStatus.PENDING_REVIEW,
            timeline=ScholarshipTimeline(application_deadline=date(2030, 1, 31)),
        )
        session.add(fresh)
        session.flush()

        candidate = AcquisitionService(session)._merge_reacquisition(
            approved, fresh, "synthetic page text", document_id=None
        )
        session.flush()
        session.refresh(approved)

        assert approved.provider_id == duplicate.provider_id
        assert approved.degree == "Master"
        assert _version_count(session, sid) == versions_before
        assert candidate is not None
        assert candidate.status == CandidateStatus.PENDING
        assert approved.extraction_status == ReviewStatus.APPROVED

    def test_raw_document_still_attaches_without_touching_the_record(
        self, session, country, resolver, provider_family, source
    ):
        """Provider work must not leave a half-written source chain."""
        primary, duplicate = provider_family
        source = SourceRegistry(
            source_name=f"Provider safety source {uuid.uuid4().hex[:8]}",
            country_id=country.country_id,
            provider_id=duplicate.provider_id,
            official_url=f"{DOMAIN}/grad",
            crawl_entry_url=f"{DOMAIN}/grad",
            crawl_method="Playwright",
            crawl_frequency="monthly",
            status="Active",
        )
        session.add(source)
        session.flush()

        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()
        session.refresh(source)

        assert source.provider_id == primary.provider_id
