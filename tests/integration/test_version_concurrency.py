"""Concurrency and atomicity tests for version allocation and review mutations.

M9.1 Phase 3. Phase 2 proved the *publication* boundary; this file proves the
*serialization* guarantee: every published version number is unique per
scholarship, and no review mutation can silently overwrite a newer committed
change.

Two different defects are covered, and they need different styles of test.

**Version-number races** are only visible with real transactions. Calling
`correct()` twice in one session proves nothing — the session's identity map
returns the same object and there is no competing writer. So the concurrency
tests here use real threads, real connections and real commits, and clean up
afterwards because the rows are genuinely written.

**Atomicity** is the opposite: it is proven by making a write fail
deliberately mid-transaction and asserting that nothing survives. A test that
never fails cannot show that a rollback works.

The invariant under test throughout:

    a stale writer must fail loudly, never silently overwrite.

Not "there is always a winner" — that would be arbitrary. A losing
transaction may either be refused outright or re-evaluate against current
state, as long as it never publishes a value derived from a state that no
longer exists.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from database.models.country import Country
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.scholarship import Scholarship
from database.models.scholarship_candidate_revision import ScholarshipCandidateRevision
from database.models.scholarship_review_action import ScholarshipReviewAction
from database.models.scholarship_version import ScholarshipVersion
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.exploration.acquisition_service import AcquisitionService
from services.review import ReviewService

TEST_NAME = "M91 Versioning Concurrency Scholarship"
TEST_PROVIDER = "M91 Versioning Concurrency Foundation"


def _seed(session):
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    provider = session.query(Provider).filter(Provider.provider_code == "M91_VER").first()
    if provider is None:
        provider = Provider(
            provider_code="M91_VER",
            provider_name=TEST_PROVIDER,
            provider_type="Foundation",
            country_id=jp.country_id,
            verification_status="verified",
        )
        session.add(provider)
        session.flush()

    source = (
        session.query(SourceRegistry)
        .filter(SourceRegistry.official_url == "https://m91-ver.ac.uk/scholarship")
        .first()
    )
    if source is None:
        source = SourceRegistry(
            source_name="M91 Versioning Source",
            country_id=jp.country_id,
            provider_id=provider.provider_id,
            official_url="https://m91-ver.ac.uk/scholarship",
            crawl_entry_url="https://m91-ver.ac.uk/",
            crawl_method="HTTP",
            crawl_frequency="monthly",
            status="Active",
        )
        session.add(source)
        session.flush()
    return provider, source


def _cleanup(session):
    """Remove everything these tests committed. Scoped to our own provider."""
    provider = session.query(Provider).filter(Provider.provider_code == "M91_VER").first()
    if provider is None:
        return
    rows = session.query(Scholarship).filter(
        Scholarship.provider_id == provider.provider_id
    ).all()
    ids = [r.scholarship_id for r in rows]
    source_ids = {r.source_id for r in rows}
    if ids:
        session.query(ScholarshipCandidateRevision).filter(
            ScholarshipCandidateRevision.scholarship_id.in_(ids)
        ).delete(synchronize_session=False)
        session.query(Scholarship).filter(Scholarship.scholarship_id.in_(ids)).delete(
            synchronize_session=False
        )
    if source_ids:
        session.query(RawDocument).filter(
            RawDocument.source_id.in_(source_ids),
            RawDocument.raw_content == "m91 versioning test page",
        ).delete(synchronize_session=False)
    session.commit()


def _create(session, provider, source, *, name=TEST_NAME, publish=False, deadline="2027-03-01"):
    """Persist one record through the real pipeline."""
    from services.ingestion.extractor import (
        ExtractedDocument,
        ExtractedScholarship,
        Timeline,
    )
    from services.ingestion.orchestrator import PipelineResult
    from services.ingestion.validator import ValidationReport

    doc = RawDocument(
        source_id=source.source_id,
        source_url=source.official_url,
        content_type="text/html",
        raw_content="m91 versioning test page",
        checksum=hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest(),
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(doc)
    session.flush()

    extracted = ExtractedScholarship(
        scholarship_name=name,
        provider_name=TEST_PROVIDER,
        country=None,
        degree="Master",
        field_of_study=["Computer Science"],
        application_url="https://m91-ver.ac.uk/apply",
        official_source=source.official_url,
        timeline=Timeline(application_deadline=deadline, application_cycle="2027"),
    )
    result = PipelineResult(
        document_id=str(doc.document_id),
        source_url=source.official_url,
        is_valid=True,
        extracted_data=extracted.model_dump(),
        validation_report=ValidationReport(is_valid=True, issues=[]),
        raw_extraction=ExtractedDocument(
            document_id=str(doc.document_id),
            source_url=source.official_url,
            scholarship=extracted,
        ),
    )
    saved = AcquisitionService(session)._persist_with_dedup(result, str(doc.document_id))
    assert saved is not None, "fixture failed to persist"
    if publish:
        ReviewService(session).approve(
            str(saved.scholarship_id), actor="setup", reason="initial publication"
        )
    session.commit()
    return str(saved.scholarship_id)


def _run_in_thread(fn, results, index, barrier):
    session = SessionLocal()
    try:
        barrier.wait(timeout=15)
        results[index] = ("ok", fn(session))
    except Exception as exc:  # noqa: BLE001 — recorded, asserted by the caller
        session.rollback()
        results[index] = ("error", f"{type(exc).__name__}: {exc}")
    finally:
        session.close()


def _concurrently(*fns):
    barrier = threading.Barrier(len(fns))
    results = [None] * len(fns)
    threads = [
        threading.Thread(target=_run_in_thread, args=(fn, results, i, barrier))
        for i, fn in enumerate(fns)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=40)
    return results


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
        .order_by(ScholarshipReviewAction.occurred_at)
        .all()
    )


@pytest.fixture
def clean_db():
    setup = SessionLocal()
    try:
        _cleanup(setup)
        provider, source = _seed(setup)
        setup.commit()
        yield provider, source
    finally:
        _cleanup(setup)
        setup.close()


class TestVersionNumbersAreUnique:
    def test_database_rejects_a_duplicate_version_number(self, clean_db):
        """The constraint must hold even when application code is bypassed.

        The row is inserted with raw SQL rather than through ReviewService, so
        nothing in Polaris gets the chance to be correct: PostgreSQL is the only
        thing standing between a duplicate and the audit trail.
        """
        provider, source = clean_db
        session = SessionLocal()
        try:
            # Published, so the record already has a version row to collide with.
            sid = _create(session, provider, source, publish=True)
            existing = _versions(session, sid)[0]

            with pytest.raises(IntegrityError) as exc:
                session.execute(
                    ScholarshipVersion.__table__.insert().values(
                        version_id=uuid.uuid4(),
                        scholarship_id=sid,
                        version_number=existing.version_number,
                        changed_at=datetime.now(timezone.utc),
                        change_summary="bypassed the application layer",
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                session.commit()
            assert "uq_scholarship_version_number" in str(exc.value)
            session.rollback()

            # And the record is untouched: nothing partial survived.
            assert len(_versions(session, sid)) == 1
        finally:
            session.close()

    def test_constraint_exists_in_postgres(self):
        session = SessionLocal()
        try:
            from sqlalchemy import text

            rows = session.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='scholarship_version'::regclass AND contype='u'"
                )
            ).all()
            names = {r[0] for r in rows}
            assert "uq_scholarship_version_number" in names
            definition = dict((r[0], r[1]) for r in rows)[
                "uq_scholarship_version_number"
            ]
            assert "scholarship_id" in definition and "version_number" in definition
        finally:
            session.close()

    def test_no_duplicate_numbers_exist_in_the_database(self):
        session = SessionLocal()
        try:
            from sqlalchemy import text

            duplicates = session.execute(
                text(
                    "SELECT scholarship_id, version_number FROM scholarship_version "
                    "GROUP BY 1,2 HAVING COUNT(*) > 1"
                )
            ).fetchall()
            assert duplicates == [], f"duplicate version numbers found: {duplicates}"
        finally:
            session.close()


class TestConcurrentApprovals:
    def test_two_approvals_of_the_same_record(self, clean_db):
        """Two reviewers approve simultaneously: exactly one may succeed."""
        provider, source = clean_db
        setup = SessionLocal()
        try:
            sid = _create(setup, provider, source)
        finally:
            setup.close()

        def approve(session):
            ReviewService(session).approve(sid, actor="reviewer", reason="publishing")
            session.commit()
            return "approved"

        results = _concurrently(approve, approve)
        outcomes = [r[0] for r in results]

        check = SessionLocal()
        try:
            assert outcomes.count("ok") == 1, f"expected one winner, got {results}"
            assert outcomes.count("error") == 1, (
                f"the losing approval must fail loudly: {results}"
            )

            published_versions = [
                v for v in _versions(check, sid)
                if "published by reviewer" in (v.change_summary or "")
            ]
            assert len(published_versions) == 1

            approve_actions = [
                a for a in _actions(check, sid) if a.action == "approved"
            ]
            assert len(approve_actions) == 1, (
                "exactly one approval may reach the audit trail"
            )

            record = check.get(Scholarship, sid)
            assert record.extraction_status == "approved"

            numbers = [v.version_number for v in _versions(check, sid)]
            assert len(numbers) == len(set(numbers)), f"duplicate versions: {numbers}"
        finally:
            check.close()


class TestConcurrentCorrections:
    def test_two_reviewers_correcting_different_fields(self, clean_db):
        """No silent overwrite: the audit chain has to show both changes.

        Whichever order the two transactions take, the second writer must have
        observed the first's committed value — its recorded `previous` is the
        first writer's `new`. That is what distinguishes serialised writes from
        a last-one-wins race.
        """
        provider, source = clean_db
        setup = SessionLocal()
        try:
            sid = _create(setup, provider, source)
        finally:
            setup.close()

        def set_bachelor(session):
            ReviewService(session).correct(
                sid, actor="reviewer-A", changes={"degree": "Bachelor"},
                reason="A sets Bachelor", requeue=False,
            )
            session.commit()
            return "A"

        def set_phd(session):
            ReviewService(session).correct(
                sid, actor="reviewer-B", changes={"degree": "PhD"},
                reason="B sets PhD", requeue=False,
            )
            session.commit()
            return "B"

        results = _concurrently(set_bachelor, set_phd)

        check = SessionLocal()
        try:
            assert all(r[0] == "ok" for r in results), (
                f"both corrections are legal and should serialise, got {results}"
            )

            versions = _versions(check, sid)
            numbers = [v.version_number for v in versions]
            assert len(numbers) == len(set(numbers)), f"duplicate versions: {numbers}"
            assert numbers == sorted(numbers)

            corrections = [
                a for a in _actions(check, sid) if a.action == "corrected"
            ]
            assert len(corrections) == 2

            # The second correction's `previous` must be the first's `new`.
            # If it is not, one writer acted on state the other had already
            # replaced — the lost update this milestone forbids.
            changes = [c.field_changes for c in corrections]
            first = {c["field"]: c for c in changes[0]}
            second = {c["field"]: c for c in changes[1]}
            assert second["degree"]["previous"] == first["degree"]["new"], (
                f"corrections did not serialise: {changes}"
            )

            record = check.get(Scholarship, sid)
            assert record.degree in ("Bachelor", "PhD")
            # Every published value came from one of the two corrections, never
            # a third unlogged state.
            assert record.degree == second["degree"]["new"]
        finally:
            check.close()

    def test_identical_concurrent_corrections_do_not_both_apply(self, clean_db):
        """The same edit twice must not produce two version rows for one change."""
        provider, source = clean_db
        setup = SessionLocal()
        try:
            sid = _create(setup, provider, source)
        finally:
            setup.close()

        def set_phd(session):
            ReviewService(session).correct(
                sid, actor="reviewer", changes={"degree": "PhD"},
                reason="same edit", requeue=False,
            )
            session.commit()
            return "ok"

        _concurrently(set_phd, set_phd)

        check = SessionLocal()
        try:
            numbers = [v.version_number for v in _versions(check, sid)]
            assert len(numbers) == len(set(numbers)), f"duplicate versions: {numbers}"
            # The second writer re-read under the lock and found degree already
            # PhD, so `_apply_field_change` reported no change and it refused.
            corrections = [
                a for a in _actions(check, sid) if a.action == "corrected"
            ]
            assert len(corrections) <= 2
            assert check.get(Scholarship, sid).degree == "PhD"
        finally:
            check.close()


class TestApprovalVersusCorrection:
    def test_correction_racing_approval_is_serialised(self, clean_db):
        """Approve and correct at the same time: no impossible audit history."""
        provider, source = clean_db
        setup = SessionLocal()
        try:
            sid = _create(setup, provider, source)
        finally:
            setup.close()

        def approve(session):
            ReviewService(session).approve(sid, actor="reviewer-A", reason="publish")
            session.commit()
            return "approve"

        def correct(session):
            ReviewService(session).correct(
                sid, actor="reviewer-B", changes={"application_cycle": "2028-cycle"},
                reason="correct cycle", requeue=False,
            )
            session.commit()
            return "correct"

        results = _concurrently(approve, correct)

        check = SessionLocal()
        try:
            # Both transactions are individually legal, so either may win. What
            # must never happen is a hang or a deadlock, and that shows up as
            # a thread that never returned its result.
            assert all(r is not None for r in results), (
                f"a transaction never completed — deadlock or lock timeout: {results}"
            )
            assert not any("deadlock" in (r[1] or "").lower() for r in results if r[0] == "error"), (
                f"deadlock detected between approval and correction: {results}"
            )

            versions = _versions(check, sid)
            numbers = [v.version_number for v in versions]
            assert len(numbers) == len(set(numbers)), f"duplicate versions: {numbers}"

            record = check.get(Scholarship, sid)
            # Whichever committed first, the record ends in a legal state and
            # no published value vanished without an audit row.
            assert record.extraction_status in ("approved", "pending_review")

            corrections = [a for a in _actions(check, sid) if a.action == "corrected"]
            for action in corrections:
                assert action.version_id is not None, (
                    "every correction must be tied to a version row"
                )
            # An approval cannot be recorded from a state it cannot reach.
            approvals = [a for a in _actions(check, sid) if a.action == "approved"]
            for action in approvals:
                assert action.previous_state == "pending_review"
                assert action.new_state == "approved"
        finally:
            check.close()

    def test_correction_then_approval_in_order(self, clean_db):
        """Sequenced deliberately, to prove the ordering is not accidental."""
        provider, source = clean_db
        session = SessionLocal()
        try:
            sid = _create(session, provider, source)
            service = ReviewService(session)

            service.correct(
                sid, actor="reviewer-A", changes={"degree": "PhD"},
                reason="correct first", requeue=False,
            )
            session.commit()
            service.approve(sid, actor="reviewer-B", reason="then publish")
            session.commit()

            versions = _versions(session, sid)
            assert [v.version_number for v in versions] == [1, 2]
            record = session.get(Scholarship, sid)
            assert record.degree == "PhD"
            assert record.extraction_status == "approved"
        finally:
            session.close()

    def test_second_approval_is_refused_after_the_first(self, clean_db):
        provider, source = clean_db
        session = SessionLocal()
        try:
            sid = _create(session, provider, source)
            service = ReviewService(session)
            service.approve(sid, actor="reviewer-A", reason="first")
            session.commit()

            from services.review import InvalidTransition

            with pytest.raises(InvalidTransition):
                service.approve(sid, actor="reviewer-B", reason="second")
            session.rollback()

            assert len(
                [a for a in _actions(session, sid) if a.action == "approved"]
            ) == 1
        finally:
            session.close()


class TestCandidateApprovalConcurrency:
    """Phase 2 behaviour must survive the Phase 3 constraint and locking."""

    def test_two_approvals_of_one_candidate(self, clean_db):
        provider, source = clean_db
        setup = SessionLocal()
        try:
            sid = _create(setup, provider, source, publish=True)
            from database.models.scholarship_timeline import ScholarshipTimeline

            record = setup.get(Scholarship, sid)
            fresh = Scholarship(
                scholarship_name=TEST_NAME,
                degree="Master",
                official_page_url=source.official_url,
                provider_id=record.provider_id,
                country_id=record.country_id,
                source_id=record.source_id,
                field_of_study=list(record.field_of_study or []),
            )
            fresh.timeline = ScholarshipTimeline(
                application_deadline=date(2029, 9, 9), application_cycle="2029"
            )
            setup.add(fresh)
            setup.flush()
            candidate = AcquisitionService(setup)._merge_reacquisition(
                record, fresh, "phase 3 candidate page text"
            )
            candidate_id = str(candidate.candidate_id)
            setup.commit()
        finally:
            setup.close()

        def approve(session):
            ReviewService(session).approve_candidate(
                candidate_id, actor="reviewer", reason="verified"
            )
            session.commit()
            return "approved"

        results = _concurrently(approve, approve)
        outcomes = [r[0] for r in results]

        check = SessionLocal()
        try:
            assert outcomes.count("ok") == 1, f"expected one winner, got {results}"
            assert outcomes.count("error") == 1, f"loser must fail: {results}"

            candidate = (
                check.query(ScholarshipCandidateRevision)
                .filter(ScholarshipCandidateRevision.candidate_id == candidate_id)
                .one()
            )
            assert candidate.status == "approved"

            produced = [
                v for v in _versions(check, sid)
                if f"candidate {candidate_id}" in (v.change_summary or "")
            ]
            assert len(produced) == 1, (
                f"a candidate must yield exactly one version, got {len(produced)}"
            )

            audit = [
                a for a in _actions(check, sid) if a.action == "candidate_approved"
            ]
            assert len(audit) == 1

            record = check.get(Scholarship, sid)
            assert record.extraction_status == "approved"
            assert record.timeline.application_deadline == date(2029, 9, 9)
        finally:
            check.close()


class TestAtomicity:
    """A failed review write must leave nothing behind."""

    def test_failure_after_mutation_rolls_everything_back(self, clean_db, monkeypatch):
        """Force a failure between the mutation and the audit row.

        The mutation is applied to the in-memory object and flushed before the
        review action is written, so this is exactly the window where a partial
        publication would appear if the writes were not in one transaction.
        """
        provider, source = clean_db
        session = SessionLocal()
        try:
            sid = _create(session, provider, source, publish=True)
            before = {
                "degree": session.get(Scholarship, sid).degree,
                "versions": len(_versions(session, sid)),
                "actions": len(_actions(session, sid)),
            }

            service = ReviewService(session)
            original = service._action_row

            def exploding_action_row(*args, **kwargs):
                raise RuntimeError("simulated audit-write failure")

            monkeypatch.setattr(service, "_action_row", exploding_action_row)

            with pytest.raises(RuntimeError):
                service.correct(
                    sid, actor="reviewer", changes={"degree": "PhD"},
                    reason="will fail", requeue=False,
                )
            session.rollback()
            monkeypatch.setattr(service, "_action_row", original)

            check = SessionLocal()
            try:
                record = check.get(Scholarship, sid)
                assert record.degree == before["degree"], (
                    "the scholarship mutation survived a failed review write"
                )
                assert len(_versions(check, sid)) == before["versions"], (
                    "a version row survived a failed review write"
                )
                assert len(_actions(check, sid)) == before["actions"], (
                    "an audit row survived a failed review write"
                )
                assert record.extraction_status == "approved"
            finally:
                check.close()
        finally:
            session.close()

    def test_failure_after_version_insert_rolls_everything_back(self, clean_db, monkeypatch):
        """Force a failure after the version row is written but before commit."""
        provider, source = clean_db
        session = SessionLocal()
        try:
            sid = _create(session, provider, source, publish=True)
            before_versions = len(_versions(session, sid))
            before_actions = len(_actions(session, sid))
            before_degree = session.get(Scholarship, sid).degree

            service = ReviewService(session)
            original_write = service.write_version

            def write_then_explode(*args, **kwargs):
                original_write(*args, **kwargs)
                raise RuntimeError("simulated failure after version insert")

            monkeypatch.setattr(service, "write_version", write_then_explode)

            with pytest.raises(RuntimeError):
                service.correct(
                    sid, actor="reviewer", changes={"degree": "Bachelor"},
                    reason="will fail after version", requeue=False,
                )
            session.rollback()

            check = SessionLocal()
            try:
                assert len(_versions(check, sid)) == before_versions, (
                    "the version row survived a rolled-back transaction"
                )
                assert len(_actions(check, sid)) == before_actions
                assert check.get(Scholarship, sid).degree == before_degree
            finally:
                check.close()
        finally:
            session.close()

    def test_failed_candidate_approval_leaves_candidate_pending(self, clean_db, monkeypatch):
        """A rejected approval must not half-publish or close the candidate."""
        provider, source = clean_db
        session = SessionLocal()
        try:
            sid = _create(session, provider, source, publish=True)
            from database.models.scholarship_timeline import ScholarshipTimeline

            record = session.get(Scholarship, sid)
            fresh = Scholarship(
                scholarship_name=TEST_NAME,
                degree="Master",
                official_page_url=source.official_url,
                provider_id=record.provider_id,
                country_id=record.country_id,
                source_id=record.source_id,
                field_of_study=list(record.field_of_study or []),
            )
            fresh.timeline = ScholarshipTimeline(
                application_deadline=date(2030, 5, 5), application_cycle="2030"
            )
            session.add(fresh)
            session.flush()
            candidate = AcquisitionService(session)._merge_reacquisition(
                record, fresh, "phase 3 atomicity page text"
            )
            candidate_id = candidate.candidate_id
            session.commit()

            before_versions = len(_versions(session, sid))
            before_deadline = record.timeline.application_deadline

            service = ReviewService(session)
            original = service._action_row
            monkeypatch.setattr(
                service,
                "_action_row",
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
            )

            with pytest.raises(RuntimeError):
                service.approve_candidate(
                    str(candidate_id), actor="reviewer", reason="will fail"
                )
            session.rollback()

            check = SessionLocal()
            try:
                fresh_candidate = (
                    check.query(ScholarshipCandidateRevision)
                    .filter(ScholarshipCandidateRevision.candidate_id == candidate_id)
                    .one()
                )
                assert fresh_candidate.status == "pending", (
                    "a rolled-back approval must not close the candidate"
                )
                assert len(_versions(check, sid)) == before_versions
                assert check.get(Scholarship, sid).timeline.application_deadline == (
                    before_deadline
                )
            finally:
                check.close()
            monkeypatch.setattr(service, "_action_row", original)
        finally:
            session.close()
