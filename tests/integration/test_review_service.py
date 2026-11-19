"""Integration tests for the review / curation domain.

These exercise the real state machine against a real database, because the
properties that matter here are transactional: an audit row, a version row
and a status change must land together, or the trail is worthless.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_review_action import ScholarshipReviewAction
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.scholarship_version import ScholarshipVersion
from database.models.source_registry import SourceRegistry
from services.review import (
    InvalidFieldValue,
    InvalidTransition,
    NotPublishable,
    ReviewService,
    ReviewStatus,
)


@pytest.fixture
def session(exploration_session):
    """The isolated session supplied by conftest."""
    return exploration_session


@pytest.fixture
def service(session):
    return ReviewService(session)


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


def _origin_refs(session, jp_country):
    """A provider and a source for the test record.

    Created here rather than read from the database because
    ``exploration_session`` deliberately empties the country's exploration
    state, which is exactly what makes these tests independent of whatever a
    real run left behind. Cached per session so the many test cases in this
    module share one provenance chain.
    """
    cached = getattr(session, "_review_test_origin_refs", None)
    if cached is not None:
        return cached

    from database.models.enums import ProviderType

    suffix = uuid.uuid4().hex[:8]
    provider = Provider(
        provider_code=f"TEST_{suffix}".upper()[:32],
        provider_name="Ministry of Education, Japan",
        provider_type=ProviderType.GOVERNMENT,
        country_id=jp_country.country_id,
        official_url="https://www.studyinjapan.go.jp/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Study in Japan {suffix}",
        country_id=jp_country.country_id,
        official_url=f"https://www.studyinjapan.go.jp/{suffix}/",
        crawl_entry_url=f"https://www.studyinjapan.go.jp/{suffix}/en/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()

    session._review_test_origin_refs = (provider, source)
    return provider, source


def make_scholarship(session, jp_country, **overrides):
    """A record good enough to publish, so gates don't mask state-machine bugs."""
    provider, source = _origin_refs(session, jp_country)
    fields = dict(
        scholarship_name="Monbukagakusho Scholarship 2027",
        provider_id=provider.provider_id,
        country_id=jp_country.country_id,
        source_id=source.source_id,
        official_page_url="https://www.studyinjapan.go.jp/en/",
        application_url="https://www.studyinjapan.go.jp/en/apply/",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Engineering"],
        extraction_status=ReviewStatus.PENDING_REVIEW,
        provenance_origin="exploration",
    )
    fields.update(overrides)
    scholarship = Scholarship(**fields)
    session.add(scholarship)
    session.flush()
    return scholarship


# ---------------------------------------------------------------- transitions


class TestApproval:
    def test_approve_publishes_and_audits(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        outcome = service.approve(
            str(scholarship.scholarship_id), actor="alice",
            reason="verified against official page",
        )
        session.commit()

        assert outcome.previous_state == ReviewStatus.PENDING_REVIEW
        assert outcome.new_state == ReviewStatus.APPROVED
        assert scholarship.extraction_status == ReviewStatus.APPROVED
        assert scholarship.reviewed_by == "alice"
        assert scholarship.reviewed_at is not None

        actions = service.history(str(scholarship.scholarship_id))
        assert [a.action for a in actions] == ["approved"]
        assert actions[0].actor == "alice"
        assert actions[0].reason == "verified against official page"
        assert actions[0].previous_state == ReviewStatus.PENDING_REVIEW

    def test_approval_writes_a_version(self, service, session, jp_country):
        """Publication is version 1 of an auditable history."""
        scholarship = make_scholarship(session, jp_country)
        service.approve(str(scholarship.scholarship_id), actor="alice")
        session.commit()

        versions = service.versions(str(scholarship.scholarship_id))
        assert len(versions) == 1
        assert versions[0].version_number == 1
        assert "published by alice" in versions[0].change_summary

    def test_approval_stores_the_quality_snapshot(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        service.approve(str(scholarship.scholarship_id), actor="alice")
        session.commit()
        assert scholarship.quality_report["publishable"] is True


class TestApprovalRefusal:
    def test_unidentifiable_record_cannot_be_approved(self, service, session, jp_country):
        """The M8 'Unknown Scholarship' case must be impossible to publish."""
        scholarship = make_scholarship(session, jp_country, scholarship_name="Unknown Scholarship")
        with pytest.raises(NotPublishable) as exc:
            service.approve(str(scholarship.scholarship_id), actor="alice")
        assert "identity" in str(exc.value)

    def test_nameless_record_never_reaches_the_database(self, session, jp_country):
        """Identity is enforced twice, on purpose.

        The extractor validator refuses a nameless record, and the column is
        NOT NULL. Either alone would do; together they mean an unidentified
        scholarship cannot be stored at all, so there is nothing for a
        reviewer to publish by accident.
        """
        with pytest.raises(IntegrityError):
            make_scholarship(session, jp_country, scholarship_name=None)
        session.rollback()

    def test_untraceable_record_cannot_be_approved(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country, official_page_url="")
        with pytest.raises(NotPublishable) as exc:
            service.approve(str(scholarship.scholarship_id), actor="alice")
        assert "official_source" in str(exc.value)

    def test_identity_and_source_are_never_overridable(self, service, session, jp_country):
        """Even an explicit override cannot publish an untraceable record."""
        scholarship = make_scholarship(session, jp_country, scholarship_name="Unknown Scholarship")
        with pytest.raises(NotPublishable) as exc:
            service.approve(
                str(scholarship.scholarship_id), actor="alice",
                reason="trust me", override_quality=True,
            )
        assert "never be overridden" in str(exc.value)

    def test_missing_degree_is_publishable_without_an_override(self, service, session, jp_country):
        """Degree became a soft field: many pages never state a level.

        Refusing those records kept verifiable awards out of the catalogue, so a
        null degree now publishes with the level reported as unknown.
        """
        scholarship = make_scholarship(session, jp_country, degree=None)
        outcome = service.approve(str(scholarship.scholarship_id), actor="alice")
        session.commit()
        assert outcome.new_state == ReviewStatus.APPROVED
        assert scholarship.degree is None
        assert not scholarship.quality_report.get("overridden_fields")

    def test_override_requires_a_reason(self, service, session, jp_country):
        # A conflicting deadline is overridable, so it carries the
        # override-reason contract that degree used to test.
        scholarship = make_scholarship(
            session,
            jp_country,
            conflicts=[
                {"field": "application_deadline", "values": ["2027-01-15", "2027-01-31"]}
            ],
        )
        with pytest.raises(NotPublishable) as exc:
            service.approve(
                str(scholarship.scholarship_id), actor="alice", override_quality=True
            )
        assert "requires a reason" in str(exc.value)

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/scholarships",
            "https://www.example.com/scholarships",
            "https://example.org/award",
            "http://localhost:8000/scholarship",
            "http://127.0.0.1/award",
            "https://scholarship.test/",
            "https://example.invalid/award",
        ],
    )
    def test_placeholder_official_source_cannot_be_approved(
        self, service, session, jp_country, url
    ):
        """The catalogue published a test record sourced from example.com.

        `official_page_url` being non-empty was the whole check, and a reserved
        test name is non-empty, so nothing stopped it. The host decides now.
        """
        scholarship = make_scholarship(session, jp_country, official_page_url=url)
        with pytest.raises(NotPublishable) as exc:
            service.approve(str(scholarship.scholarship_id), actor="alice")
        assert "official_source" in str(exc.value)

    def test_placeholder_source_is_not_overridable(self, service, session, jp_country):
        """Like every other provenance failure, an override must not bypass it."""
        scholarship = make_scholarship(
            session, jp_country, official_page_url="https://example.com/x"
        )
        with pytest.raises(NotPublishable) as exc:
            service.approve(
                str(scholarship.scholarship_id), actor="alice",
                reason="the reviewer says it is fine", override_quality=True,
            )
        assert "never be overridden" in str(exc.value)

    def test_refused_approval_leaves_no_trace_of_approval(
        self, service, session, jp_country
    ):
        """Status, version history and audit history must all be untouched.

        A refusal that had already written a version or an `approved` audit row
        would leave a record looking published to a later reader and to the
        trail, while the status said otherwise.
        """
        scholarship = make_scholarship(
            session, jp_country, official_page_url="https://example.com/x"
        )
        sid = str(scholarship.scholarship_id)
        session.commit()

        with pytest.raises(NotPublishable):
            service.approve(sid, actor="alice", reason="looks fine to me")
        session.rollback()

        # Re-read from the database rather than trusting the in-memory object
        # the refused call had locked.
        session.expire_all()
        row = service.get(sid)
        assert row.extraction_status == ReviewStatus.PENDING_REVIEW
        assert row.reviewed_by is None
        assert row.reviewed_at is None
        # The refusal must not have stored a "publishable" snapshot either.
        assert (row.quality_report or {}).get("publishable") is not True

        # No version row and no `approved` audit row: the trail must not claim
        # an approval that did not happen.
        assert service.versions(sid) == []
        assert service.history(sid) == []

    def test_an_unfamiliar_but_real_official_source_still_approves(
        self, service, session, jp_country
    ):
        """Scope discipline: the rule is reserved names, not unfamiliar hosts."""
        for url in (
            "https://www.studyinjapan.go.jp/en/",
            "https://www.daad.de/en/studying-in-germany/scholarships/",
            "https://exampleuniversity.edu/scholarships",
            "https://www.myexample.org/award",
            "https://notexample.com/scholarship",
        ):
            scholarship = make_scholarship(session, jp_country, official_page_url=url)
            outcome = service.approve(
                str(scholarship.scholarship_id), actor="alice",
                reason="verified on the provider's own page",
            )
            session.commit()
            assert outcome.new_state == ReviewStatus.APPROVED, url


class TestRejection:
    def test_reject_removes_from_publication_and_audits(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        outcome = service.reject(
            str(scholarship.scholarship_id), actor="bob", reason="duplicate of an existing record"
        )
        session.commit()

        assert outcome.new_state == ReviewStatus.REJECTED
        assert scholarship.extraction_status == ReviewStatus.REJECTED
        actions = service.history(str(scholarship.scholarship_id))
        assert actions[0].action == "rejected"
        assert actions[0].reason == "duplicate of an existing record"

    def test_rejection_requires_a_reason(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        with pytest.raises(InvalidTransition):
            service.reject(str(scholarship.scholarship_id), actor="bob", reason="   ")

    def test_approved_record_can_be_rejected(self, service, session, jp_country):
        """Publishing something wrong must always be reversible."""
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.approve(sid, actor="alice")
        session.commit()

        service.reject(sid, actor="bob", reason="deadline was wrong")
        session.commit()
        assert scholarship.extraction_status == ReviewStatus.REJECTED


class TestCorrections:
    def test_request_correction_keeps_record_out_of_publication(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        outcome = service.request_correction(
            str(scholarship.scholarship_id), actor="carol",
            reason="deadline looks wrong", fields=["deadline"],
        )
        session.commit()
        assert outcome.new_state == ReviewStatus.NEEDS_CORRECTION
        assert scholarship.extraction_status == ReviewStatus.NEEDS_CORRECTION
        assert outcome.field_changes[0]["requested_fields"] == ["deadline"]

    def test_request_correction_requires_a_reason(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        with pytest.raises(InvalidTransition):
            service.request_correction(str(scholarship.scholarship_id), actor="carol", reason="")

    def test_correction_records_previous_value_and_creates_a_version(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        session.add(ScholarshipTimeline(
            scholarship_id=scholarship.scholarship_id,
            application_deadline=date(2027, 3, 1),
        ))
        session.flush()
        sid = str(scholarship.scholarship_id)
        service.approve(sid, actor="alice")
        session.commit()

        outcome = service.correct(
            sid, actor="carol",
            changes={"deadline": date(2027, 4, 15)},
            reason="official page updated",
            requeue=False,
        )
        session.commit()

        assert outcome.field_changes == [
            {"field": "application_deadline", "previous": "2027-03-01", "new": "2027-04-15"}
        ]
        assert scholarship.timeline.application_deadline == date(2027, 4, 15)

        versions = service.versions(sid)
        assert len(versions) == 2
        assert versions[0].version_number == 1
        assert versions[1].version_number == 2
        assert "corrected by carol" in versions[1].change_summary

    def test_placeholder_official_url_is_refused_even_without_requeue(
        self, service, session, jp_country
    ):
        """The approval gate is not enough on its own, so the value is refused.

        A correction with `requeue=False` keeps an approved record approved, so
        it never passes back through `approve()` and its quality gate. Without a
        check on the value itself, this call would repoint a live record's trust
        anchor at a reserved test host and leave it published.
        """
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.approve(sid, actor="alice")
        session.commit()
        before = scholarship.official_page_url

        with pytest.raises(InvalidFieldValue) as exc:
            service.correct(
                sid, actor="carol",
                changes={"official_page_url": "https://example.com/scholarship"},
                reason="pasting the page from the ticket",
                requeue=False,
            )
        assert "placeholder host" in str(exc.value)
        session.rollback()

        assert service.get(sid).extraction_status == ReviewStatus.APPROVED
        assert service.get(sid).official_page_url == before
        # Only the original publication is in the history; the refused edit is
        # not recorded as a correction that happened.
        assert [a.action for a in service.history(sid)] == ["approved"]
        assert len(service.versions(sid)) == 1

    def test_placeholder_application_url_is_refused_too(self, service, session, jp_country):
        """The apply link is the other URL a reader is sent to; same rule."""
        scholarship = make_scholarship(session, jp_country)
        with pytest.raises(InvalidFieldValue) as exc:
            service.correct(
                str(scholarship.scholarship_id), actor="carol",
                changes={"application_url": "http://localhost/apply"},
                reason="local copy for the demo",
            )
        assert "placeholder host" in str(exc.value)

    def test_a_real_official_url_can_still_be_corrected(self, service, session, jp_country):
        """Regression: the new check must not block a legitimate correction."""
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        outcome = service.correct(
            sid, actor="carol",
            changes={"official_page_url": "https://www.studyinjapan.go.jp/en/scholarships/"},
            reason="the provider moved the page",
            requeue=False,
        )
        session.commit()
        assert outcome.field_changes[0]["field"] == "official_page_url"
        assert scholarship.official_page_url == "https://www.studyinjapan.go.jp/en/scholarships/"

    def test_correction_can_add_a_timeline_to_a_record_that_lacked_one(self, service, session, jp_country):
        """A thin extraction has no timeline row, but the reviewer must still be
        able to supply the deadline that matters most."""
        scholarship = make_scholarship(session, jp_country)
        assert scholarship.timeline is None

        outcome = service.correct(
            str(scholarship.scholarship_id), actor="carol",
            changes={"deadline": date(2027, 5, 1)}, reason="read off the official page",
        )
        session.commit()
        assert outcome.field_changes[0]["previous"] is None
        assert scholarship.timeline.application_deadline == date(2027, 5, 1)

    def test_correction_preserves_history_not_overwrite(self, service, session, jp_country):
        """The old value must remain readable in the audit trail."""
        scholarship = make_scholarship(session, jp_country)
        timeline = ScholarshipTimeline(
            scholarship_id=scholarship.scholarship_id,
            application_deadline=date(2027, 3, 1),
        )
        session.add(timeline)
        session.flush()
        sid = str(scholarship.scholarship_id)
        service.approve(sid, actor="alice")
        service.correct(
            sid, actor="carol", changes={"deadline": date(2027, 4, 15)},
            reason="updated", requeue=False,
        )
        session.commit()

        actions = service.history(sid)
        corrected = actions[-1]
        assert corrected.field_changes[0]["previous"] == "2027-03-01"
        assert corrected.field_changes[0]["new"] == "2027-04-15"

    def test_correction_requeues_for_another_pass(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.approve(sid, actor="alice")
        outcome = service.correct(
            sid, actor="carol", changes={"funding_type": "Partial Funded"},
            reason="page says partial", requeue=True,
        )
        session.commit()
        assert outcome.new_state == ReviewStatus.PENDING_REVIEW
        assert scholarship.extraction_status == ReviewStatus.PENDING_REVIEW

    def test_unknown_field_is_refused_not_silently_ignored(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        with pytest.raises(InvalidTransition) as exc:
            service.correct(
                str(scholarship.scholarship_id), actor="carol",
                changes={"not_a_field": 1}, reason="typo",
            )
        assert "not an editable field" in str(exc.value)
        assert "not_a_field" in str(exc.value)

    def test_no_op_correction_is_refused(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        with pytest.raises(InvalidTransition):
            service.correct(
                str(scholarship.scholarship_id), actor="carol",
                changes={"degree": "Master"}, reason="no actual change",
            )


class TestInvalidTransitions:
    def test_cannot_approve_a_rejected_record(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.reject(sid, actor="bob", reason="not a scholarship")
        session.commit()

        with pytest.raises(InvalidTransition) as exc:
            service.approve(sid, actor="alice")
        assert "cannot move scholarship" in str(exc.value)

    def test_unknown_scholarship_is_reported(self, service):
        with pytest.raises(InvalidTransition):
            service.approve(str(uuid.uuid4()), actor="alice")

    def test_rejected_record_is_reopenable_via_correction(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.reject(sid, actor="bob", reason="misidentified")
        session.commit()

        outcome = service.correct(
            sid, actor="carol", changes={"scholarship_name": "Correct Name 2027"},
            reason="re-checked the page",
        )
        session.commit()
        assert outcome.new_state == ReviewStatus.PENDING_REVIEW


class TestSubmission:
    def test_submission_records_arrival(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        service.record_submission(scholarship, actor="pipeline")
        session.commit()
        assert [a.action for a in service.history(str(scholarship.scholarship_id))] == ["submitted"]

    def test_submission_is_idempotent(self, service, session, jp_country):
        """Re-running acquisition must not pile up submission rows."""
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.record_submission(scholarship, actor="pipeline")
        service.record_submission(scholarship, actor="pipeline")
        session.commit()
        assert len(service.history(sid)) == 1


class TestAuditTrail:
    def test_every_transition_leaves_a_trail(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.request_correction(sid, actor="carol", reason="check deadline")
        service.correct(
            sid, actor="carol", changes={"deadline": date(2027, 5, 1)},
            reason="confirmed on page",
        )
        service.approve(sid, actor="alice", reason="good")
        session.commit()

        actions = service.history(sid)
        assert [a.action for a in actions] == ["needs_correction", "corrected", "approved"]
        # Each row records where it came from and where it went.
        assert actions[0].previous_state == ReviewStatus.PENDING_REVIEW
        assert actions[1].previous_state == ReviewStatus.NEEDS_CORRECTION
        assert actions[2].previous_state == ReviewStatus.PENDING_REVIEW
        assert all(a.actor for a in actions)
        assert all(a.occurred_at for a in actions)

    def test_audit_rows_cascade_with_the_scholarship(self, service, session, jp_country):
        """Deleting a record takes its trail with it.

        ON DELETE CASCADE means no orphan audit rows can be left behind
        pointing at a scholarship that no longer exists.
        """
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.approve(sid, actor="alice")
        session.flush()

        session.delete(scholarship)
        session.flush()
        assert session.query(ScholarshipReviewAction).filter(
            ScholarshipReviewAction.scholarship_id == uuid.UUID(sid)
        ).count() == 0
        session.rollback()


class TestReviewQueue:
    def test_queue_is_filterable_by_state(self, service, session, jp_country):
        pending = make_scholarship(session, jp_country)
        make_scholarship(session, jp_country, extraction_status=ReviewStatus.REJECTED)
        session.commit()

        rows, total = service.list_for_review(
            state=ReviewStatus.PENDING_REVIEW,
            country_id=str(jp_country.country_id),
        )
        assert total == 1
        assert rows[0].scholarship_id == pending.scholarship_id

    def test_queue_is_filterable_by_origin(self, service, session, jp_country):
        make_scholarship(session, jp_country, provenance_origin="exploration")
        make_scholarship(session, jp_country, provenance_origin="seed_script")
        session.commit()

        _, total = service.list_for_review(
            state=None, origin="exploration", country_id=str(jp_country.country_id),
        )
        assert total == 1

    def test_queue_is_scoped_to_a_country(self, service, session, jp_country):
        """A reviewer triages one country; the queue must not span all of them."""
        pending = make_scholarship(session, jp_country)
        session.commit()

        rows, total = service.list_for_review(
            state=ReviewStatus.PENDING_REVIEW,
            country_id=str(jp_country.country_id),
            limit=500,
        )
        # The shared development database holds real rows from other countries;
        # what matters is that none of them appear in this country's queue.
        assert {r.scholarship_id for r in rows} <= {pending.scholarship_id}
        assert total <= 1

    def test_all_states_returns_every_record_for_metrics(self, service, session, jp_country):
        make_scholarship(session, jp_country)
        make_scholarship(session, jp_country, extraction_status=ReviewStatus.REJECTED)
        session.commit()
        _, total = service.list_for_review(
            state=None, country_id=str(jp_country.country_id),
        )
        assert total == 2


class TestVersioning:
    def test_version_numbers_are_monotonic(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.approve(sid, actor="alice")
        for n, value in enumerate([date(2027, 4, 1), date(2027, 5, 1)], start=2):
            service.correct(
                sid, actor="carol", changes={"deadline": value},
                reason=f"rev {n}", requeue=False,
            )
        session.commit()
        numbers = [v.version_number for v in service.versions(sid)]
        assert numbers == [1, 2, 3]

    def test_versions_link_back_to_their_audit_row(self, service, session, jp_country):
        scholarship = make_scholarship(session, jp_country)
        sid = str(scholarship.scholarship_id)
        service.approve(sid, actor="alice")
        session.commit()

        action = service.history(sid)[-1]
        assert action.version_id is not None
        assert session.query(ScholarshipVersion).filter(
            ScholarshipVersion.version_id == action.version_id
        ).count() == 1
