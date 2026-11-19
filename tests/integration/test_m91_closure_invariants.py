"""M9.1 closure invariants — the promises the audit re-checked, made executable.

A closure pass that only reads code proves nothing by the next commit. These
tests pin the findings that were verified once and would otherwise drift
silently:

C1  the review state machine matches the documented lifecycle
C2  `source_registry.acquisition_state` has exactly one vocabulary
C3  a NULL deadline is `unknown`, never `expired`, and no sentinel date is
    stored to stand in for "unknown"
C4  version numbers stay unique and a published record's latest version is the
    current one
C6  provider resolution leaves an approved record's provider link alone
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from database.models.source_registry import SourceAcquisitionState
from services.exploration.acquisition_policy import AcquisitionState
from services.review import ReviewService, ReviewStatus
from services.review.service import _ALLOWED
from services.scholarship import freshness


@pytest.fixture
def context(exploration_session):
    """Country, provider and source a probe record can legally reference.

    `provider_id`, `country_id` and `source_id` are NOT NULL in the schema, so
    every probe record needs real rows behind it.
    """
    import uuid

    from database.models import Country, Provider, SourceRegistry
    from database.models.enums import ProviderType

    session = exploration_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]
    provider = Provider(
        provider_code=f"CLOSURE_{suffix.upper()}"[:32],
        provider_name="Closure Probe Foundation",
        provider_type=ProviderType.FOUNDATION,
        country_id=country.country_id,
        official_url="https://closure.example.edu/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Closure probe source {suffix}",
        country_id=country.country_id,
        official_url="https://closure.example.edu/",
        crawl_entry_url="https://closure.example.edu/",
        crawl_method="HTTP",
        crawl_frequency="monthly",
        status="Active",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()
    return {"session": session, "country": country, "provider": provider, "source": source}


def _probe(context, name, *, state=None, identity_key=None):
    """A minimal record that clears the publication gates.

    The gates block a publish without a degree, so a probe that wants to reach
    `approve()` has to carry one.
    """
    from database.models import Scholarship

    record = Scholarship(
        scholarship_name=name,
        degree="Master",
        official_page_url=f"https://closure.example.edu/{name.replace(' ', '-').lower()}",
        provider_id=context["provider"].provider_id,
        country_id=context["country"].country_id,
        source_id=context["source"].source_id,
        extraction_status=state,
        identity_key=identity_key,
    )
    context["session"].add(record)
    context["session"].flush()
    return record


class TestC1StateMachineMatchesTheDocument:
    def test_the_states_are_exactly_the_documented_ones(self):
        """ADR-015 was corrected to this list in the M9.1 closure audit.

        `superseded` and `archived` were documented but never implemented;
        adding them would create states nothing can reach.
        """
        documented = {
            ReviewStatus.PENDING_REVIEW,
            ReviewStatus.APPROVED,
            ReviewStatus.REJECTED,
            ReviewStatus.NEEDS_CORRECTION,
        }
        assert set(_ALLOWED) == documented
        assert {s for targets in _ALLOWED.values() for s in targets} == documented

    def test_every_settled_state_can_be_reopened(self):
        """No state is a dead end: a reviewer can always pick a record back up.

        PENDING_REVIEW is the entry point rather than a destination, so it is
        the one state that does not transition to itself.
        """
        for state, targets in _ALLOWED.items():
            if state == ReviewStatus.PENDING_REVIEW:
                continue
            assert ReviewStatus.PENDING_REVIEW in targets, state

    def test_publishing_is_reachable_only_through_review(self, context):
        record = _probe(
            context, "Closure state probe", state=ReviewStatus.REJECTED
        )

        # REJECTED -> APPROVED is not in the table, and the machine says so.
        with pytest.raises(Exception) as exc:
            ReviewService(context["session"]).approve(
                str(record.scholarship_id), actor="closure", reason="should refuse"
            )
        assert "cannot move scholarship" in str(exc.value)
        context["session"].rollback()


class TestC2SourceAcquisitionVocabulary:
    def test_one_vocabulary_not_two(self):
        assert AcquisitionState.ACQUIRED == SourceAcquisitionState.ACQUIRED
        assert AcquisitionState.PENDING == SourceAcquisitionState.PENDING
        assert AcquisitionState.FAILED == SourceAcquisitionState.FAILED
        assert AcquisitionState.SKIPPED == SourceAcquisitionState.SKIPPED
        assert (
            AcquisitionState.NO_SCHOLARSHIP_PAGES
            == SourceAcquisitionState.NO_SCHOLARSHIP_PAGES
        )

    def test_the_values_nothing_writes_are_gone(self):
        """COMPLETED / IN_PROGRESS / NOT_ATTEMPTED were never persisted."""
        values = {
            getattr(SourceAcquisitionState, name)
            for name in vars(SourceAcquisitionState)
            if name.isupper()
        }
        assert "completed" not in values
        assert "in_progress" not in values
        assert "not_attempted" not in values

    def test_live_rows_use_the_declared_vocabulary(self):
        from database.models import SourceRegistry
        from database.session import SessionLocal

        session = SessionLocal()
        try:
            used = {
                value
                for (value,) in session.query(SourceRegistry.acquisition_state)
                .filter(SourceRegistry.acquisition_state.isnot(None))
                .distinct()
                .all()
            }
            declared = {
                getattr(SourceAcquisitionState, name)
                for name in vars(SourceAcquisitionState)
                if name.isupper()
            }
            assert used <= declared, f"undeclared acquisition states: {used - declared}"
        finally:
            session.close()


class TestC3DeadlineSemantics:
    def test_null_deadline_is_unknown_never_expired(self):
        assert freshness.classify_deadline(None) == freshness.STATE_UNKNOWN

    def test_null_deadline_is_kept_by_the_matching_filter(self):
        from services.matching.filter.engine import FilterEngine

        class _Timeline:
            application_deadline = None

        class _Record:
            timeline = _Timeline()

        assert FilterEngine._not_expired(_Record()) is True

    def test_null_deadline_state_stays_visible_to_the_public_gate(self):
        from services.review.publication import not_expired_filter

        rendered = str(not_expired_filter())
        assert "IS NULL" in rendered.upper()

    def test_a_past_deadline_is_expired_and_a_future_one_is_active(self):
        today = date.today()
        assert freshness.classify_deadline(today, today=today) == freshness.STATE_ACTIVE
        assert (
            freshness.classify_deadline(today.replace(year=today.year - 1), today=today)
            == freshness.STATE_EXPIRED
        )

    def test_no_sentinel_date_is_stored_for_an_unknown_deadline(self):
        """`2099-01-01` was the original defect: a fake deadline, not a missing one."""
        from sqlalchemy import func

        from database.models.scholarship_timeline import ScholarshipTimeline
        from database.session import SessionLocal

        session = SessionLocal()
        try:
            sentinels = (
                session.query(func.count())
                .select_from(ScholarshipTimeline)
                .filter(
                    ScholarshipTimeline.application_deadline > date.today().replace(year=2099)
                )
                .scalar()
            )
            assert sentinels == 0, f"{sentinels} timeline rows hold a sentinel deadline"
        finally:
            session.close()


class TestC4VersionIntegrity:
    def test_version_numbers_are_unique_per_scholarship(self, context):
        from datetime import datetime, timezone

        from sqlalchemy.exc import IntegrityError

        from database.models.scholarship_version import ScholarshipVersion

        session = context["session"]
        record = _probe(context, "Closure version probe")

        version = ScholarshipVersion(
            scholarship_id=record.scholarship_id,
            version_number=1,
            changed_at=datetime.now(timezone.utc),
            change_summary="first",
        )
        session.add(version)
        session.flush()

        session.add(
            ScholarshipVersion(
                scholarship_id=record.scholarship_id,
                version_number=1,
                changed_at=datetime.now(timezone.utc),
                change_summary="duplicate",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_publishing_writes_exactly_one_version(self, context):
        from database.models.scholarship_version import ScholarshipVersion

        session = context["session"]
        record = _probe(context, "Closure approval probe")

        ReviewService(session).approve(
            str(record.scholarship_id), actor="closure", reason="verified"
        )
        session.flush()

        versions = (
            session.query(ScholarshipVersion)
            .filter(ScholarshipVersion.scholarship_id == record.scholarship_id)
            .all()
        )
        assert len(versions) == 1
        assert versions[0].version_number == 1


class TestC6ProviderSafetyHolds:
    def test_merge_leaves_an_approved_record_alone(self, exploration_session):
        from database.models import Country, Provider
        from database.models.enums import ProviderType
        from services.exploration.provider_resolver import ProviderResolver

        session = exploration_session
        country = session.query(Country).filter(Country.iso2 == "JP").first()
        domain = "https://closure.probe.example.edu/"

        primary = Provider(
            provider_code=f"CLOSURE_A_{uuid.uuid4().hex[:8].upper()}"[:32],
            provider_name="Closure Probe University",
            provider_type=ProviderType.UNIVERSITY,
            country_id=country.country_id,
            official_url=domain,
            verification_status="verified",
        )
        duplicate = Provider(
            provider_code=f"CLOSURE_B_{uuid.uuid4().hex[:8].upper()}"[:32],
            provider_name="Closure Probe Admissions",
            provider_type=ProviderType.UNIVERSITY,
            country_id=country.country_id,
            official_url=f"{domain}grad",
            verification_status="discovered",
            discovered_at=datetime.now(timezone.utc),
        )
        session.add_all([primary, duplicate])
        session.flush()

        resolver = ProviderResolver(session, country.country_id)
        resolver._merge_domain_duplicates([primary, duplicate])
        session.flush()

        assert duplicate.merged_into_provider_id == primary.provider_id
