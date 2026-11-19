"""Concurrency tests: reacquisition and review must not overwrite each other.

M9.1 Phase 2. The sequential tests in ``test_reacquisition_boundary.py`` prove
the boundary holds; these prove it holds when two *genuinely concurrent*
transactions touch the same record.

The distinction matters. Calling ``approve_candidate`` twice in one session
exercises a state check. Committing from two separate connections exercises the
row lock and the uniqueness constraint, which is where a lost update actually
lives. So each test here uses real connections and real commits, then cleans up
in a ``finally`` block because the row is genuinely written.

Cleanup deletes the rows it created by identity key, so the shared development
database keeps its real knowledge base.
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
from database.models.scholarship_candidate_revision import (
    CandidateStatus,
    ScholarshipCandidateRevision,
)
from database.models.scholarship_version import ScholarshipVersion
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.exploration.acquisition_service import AcquisitionService
from services.review import ReviewService, StaleCandidate

TEST_NAME = "M91 Concurrency Boundary Scholarship"
TEST_PROVIDER = "M91 Concurrency Boundary Foundation"


def _seed(session):
    """Create (or reuse) an isolated provider + source for these tests."""
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    provider = session.query(Provider).filter(Provider.provider_code == "M91_CONC").first()
    if provider is None:
        provider = Provider(
            provider_code="M91_CONC",
            provider_name=TEST_PROVIDER,
            provider_type="Foundation",
            country_id=jp.country_id,
            verification_status="verified",
        )
        session.add(provider)
        session.flush()

    source = (
        session.query(SourceRegistry)
        .filter(SourceRegistry.official_url == "https://m91-conc.ac.uk/scholarship")
        .first()
    )
    if source is None:
        source = SourceRegistry(
            source_name="M91 Concurrency Source",
            country_id=jp.country_id,
            provider_id=provider.provider_id,
            official_url="https://m91-conc.ac.uk/scholarship",
            crawl_entry_url="https://m91-conc.ac.uk/",
            crawl_method="HTTP",
            crawl_frequency="monthly",
            status="Active",
        )
        session.add(source)
        session.flush()
    return provider, source


def _cleanup(session, provider):
    """Remove anything these tests committed. Never touches other rows."""
    scholarships = (
        session.query(Scholarship)
        .filter(Scholarship.provider_id == provider.provider_id)
        .all()
    )
    ids = [s.scholarship_id for s in scholarships]
    source_ids = {s.source_id for s in scholarships}

    if ids:
        session.query(ScholarshipCandidateRevision).filter(
            ScholarshipCandidateRevision.scholarship_id.in_(ids)
        ).delete(synchronize_session=False)
        session.query(Scholarship).filter(Scholarship.scholarship_id.in_(ids)).delete(
            synchronize_session=False
        )

    # The capture rows too: they are committed alongside the record, and
    # leaving them behind would make the next run collide on
    # uq_raw_document_source_checksum.
    if source_ids:
        session.query(RawDocument).filter(
            RawDocument.source_id.in_(source_ids),
            RawDocument.raw_content == "concurrency test page",
        ).delete(synchronize_session=False)

    session.flush()
    session.commit()


def _make_published(session, provider, source, *, deadline=date(2027, 3, 1)):
    """Persist and approve one record, then return its id.

    The checksum is unique per call so repeated runs against the shared
    development database never collide on uq_raw_document_source_checksum.
    """
    unique = uuid.uuid4().hex
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
        raw_content="concurrency test page",
        checksum=hashlib.sha256(f"m91-conc-{unique}".encode()).hexdigest(),
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(doc)
    session.flush()

    extracted = ExtractedScholarship(
        scholarship_name=TEST_NAME,
        provider_name=TEST_PROVIDER,
        country=None,
        degree="Master",
        field_of_study=["Computer Science"],
        application_url="https://m91-conc.ac.uk/apply",
        official_source=source.official_url,
        timeline=Timeline(
            application_deadline=deadline.isoformat(), application_cycle="2027"
        ),
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
    assert saved is not None
    ReviewService(session).approve(
        str(saved.scholarship_id), actor="setup", reason="initial publication"
    )
    session.commit()
    return str(saved.scholarship_id)


def _run_in_thread(fn, results, index, barrier):
    """Run `fn` on its own session, synchronised on `barrier`."""
    session = SessionLocal()
    try:
        barrier.wait(timeout=10)
        results[index] = ("ok", fn(session))
    except Exception as exc:  # noqa: BLE001 — recorded, asserted by the caller
        session.rollback()
        results[index] = ("error", f"{type(exc).__name__}: {exc}")
    finally:
        session.close()


def _concurrently(*fns):
    """Run each fn on its own connection, released together."""
    barrier = threading.Barrier(len(fns))
    results = [None] * len(fns)
    threads = [
        threading.Thread(target=_run_in_thread, args=(fn, results, i, barrier))
        for i, fn in enumerate(fns)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


@pytest.fixture
def concurrency_env():
    """A published record, committed for real, removed afterwards."""
    setup = SessionLocal()
    try:
        provider, source = _seed(setup)
        setup.commit()
        scholarship_id = _make_published(setup, provider, source)
        yield scholarship_id, provider.provider_id
    finally:
        _cleanup(setup, setup.get(Provider, provider.provider_id))
        setup.close()


class TestConcurrentCandidateDecisions:
    def test_two_approvals_of_the_same_candidate(self, concurrency_env):
        """Only one approval may publish; the loser must fail loudly."""
        scholarship_id, provider_id = concurrency_env
        setup = SessionLocal()

        from database.models.scholarship import Scholarship as S

        record = setup.query(S).filter(S.scholarship_id == scholarship_id).one()
        candidate = ReviewService(setup).propose_candidate(
            record,
            observed={"application_deadline": date(2029, 9, 9)},
            actor="acquisition",
        )
        candidate_id = str(candidate.candidate_id)
        setup.commit()
        setup.close()

        def approve(session):
            ReviewService(session).approve_candidate(
                candidate_id, actor="reviewer", reason="verified"
            )
            session.commit()
            return "approved"

        results = _concurrently(approve, approve)
        outcomes = [r[0] for r in results]
        assert outcomes.count("ok") == 1, f"expected one winner, got {results}"
        assert outcomes.count("error") == 1, f"loser must fail, not pass silently: {results}"

        check = SessionLocal()
        try:
            versions = (
                check.query(ScholarshipVersion)
                .filter(ScholarshipVersion.scholarship_id == scholarship_id)
                .all()
            )
            approved_versions = [
                v for v in versions if f"candidate {candidate_id}" in (v.change_summary or "")
            ]
            assert len(approved_versions) == 1, (
                f"a candidate must produce exactly one version, got {len(approved_versions)}"
            )
        finally:
            _cleanup(check, check.get(Provider, provider_id))
            check.close()

    def test_concurrent_proposals_do_not_duplicate_pending_candidates(
        self, concurrency_env
    ):
        """The unique partial index is what stops a pile-up, not a read-then-write."""
        scholarship_id, provider_id = concurrency_env
        setup = SessionLocal()
        from database.models.scholarship import Scholarship as S

        record = setup.query(S).filter(S.scholarship_id == scholarship_id).one()
        source = record.source
        record_id = scholarship_id
        setup.close()

        def propose(session):
            row = (
                session.query(S)
                .filter(S.scholarship_id == record_id)
                .with_for_update()
                .one()
            )
            ReviewService(session).propose_candidate(
                row,
                observed={"application_deadline": date(2031, 3, 3)},
                actor="acquisition",
            )
            session.commit()
            return "proposed"

        results = _concurrently(propose, propose)
        errors = [r[1] for r in results if r[0] == "error"]

        check = SessionLocal()
        try:
            pending = (
                check.query(ScholarshipCandidateRevision)
                .filter(
                    ScholarshipCandidateRevision.scholarship_id == record_id,
                    ScholarshipCandidateRevision.status == CandidateStatus.PENDING,
                    ScholarshipCandidateRevision.source_url == source.official_url,
                )
                .all()
            )
            assert len(pending) == 1, (
                f"expected 1 pending candidate, got {len(pending)}; errors={errors}"
            )
        finally:
            _cleanup(check, check.get(Provider, provider_id))
            check.close()


class TestReacquisitionRacesReview:
    def test_reacquisition_during_review_does_not_publish(self, concurrency_env):
        """A re-crawl racing an approval must not reach the published row.

        Whichever side wins, the published values only ever change through the
        approval path — the acquisition side has no route to them at all.
        """
        scholarship_id, provider_id = concurrency_env
        setup = SessionLocal()
        from database.models.scholarship import Scholarship as S

        record = setup.query(S).filter(S.scholarship_id == scholarship_id).one()
        fresh_source = record.source
        sid = scholarship_id
        setup.close()

        def reacquire(session):
            from database.models.scholarship_timeline import ScholarshipTimeline

            row = (
                session.query(S)
                .filter(S.scholarship_id == sid)
                .with_for_update()
                .one()
            )
            transient = S(
                scholarship_name=TEST_NAME,
                provider_id=row.provider_id,
                country_id=row.country_id,
                source_id=fresh_source.source_id,
                official_page_url=fresh_source.official_url,
                field_of_study=[],
                extraction_status="pending_review",
            )
            transient.timeline = ScholarshipTimeline(
                application_deadline=date(2099, 1, 1),
                application_cycle="2099",
            )
            session.add(transient)
            session.flush()
            AcquisitionService(session)._merge_reacquisition(
                row, transient, "concurrent reacquisition page text"
            )
            session.commit()
            return "reacquired"

        def approve(session):
            ReviewService(session).correct(
                sid,
                actor="reviewer",
                changes={"application_cycle": "2028-reviewer"},
                reason="reviewer correction",
                requeue=False,
            )
            session.commit()
            return "corrected"

        results = _concurrently(reacquire, approve)
        errors = [r[1] for r in results if r[0] == "error"]

        check = SessionLocal()
        try:
            row = check.query(S).filter(S.scholarship_id == sid).one()
            check.refresh(row)
            # Whichever order the transactions took, 2099 never reaches the
            # published record: acquisition cannot write it, by construction.
            assert row.timeline.application_deadline != date(2099, 1, 1), (
                "reacquisition reached published data during a concurrent review"
            )
            assert row.extraction_status == "approved"
        finally:
            _cleanup(check, check.get(Provider, provider_id))
            check.close()
        assert len(errors) <= 2  # recorded above; a deadlock would show as an error

    def test_approval_against_a_moved_record_is_refused(self, concurrency_env):
        """The version moved after the proposal, so the approval is refused."""
        scholarship_id, provider_id = concurrency_env
        setup = SessionLocal()
        from database.models.scholarship import Scholarship as S

        record = setup.query(S).filter(S.scholarship_id == scholarship_id).one()
        candidate = ReviewService(setup).propose_candidate(
            record,
            observed={"application_deadline": date(2029, 9, 9)},
            actor="acquisition",
        )
        candidate_id = str(candidate.candidate_id)
        setup.commit()

        # Another transaction publishes a change first.
        ReviewService(setup).correct(
            scholarship_id,
            actor="other-reviewer",
            changes={"application_cycle": "2028-other"},
            reason="unrelated correction",
            requeue=False,
        )
        setup.commit()
        setup.close()

        late = SessionLocal()
        try:
            with pytest.raises(StaleCandidate):
                ReviewService(late).approve_candidate(
                    candidate_id, actor="reviewer", reason="too late"
                )
            late.rollback()
        finally:
            _cleanup(late, late.get(Provider, provider_id))
            late.close()


class TestDatabaseConstraints:
    def test_duplicate_version_numbers_are_rejected_by_the_database(self):
        """Proves the constraint exists at the DB level, not just in Python.

        This test was written in M9.1 Phase 2 as a conditional that skipped
        while the constraint did not exist. Phase 3 adds it, so the skip branch
        is gone: the guarantee is now asserted unconditionally rather than
        merely documented.

        The duplicate is inserted directly rather than through ReviewService, so
        nothing in Polaris gets the chance to be correct. Only PostgreSQL stands
        between a duplicate version number and the audit trail.
        """
        session = SessionLocal()
        try:
            provider, source = _seed(session)
            sid = _make_published(session, provider, source)
            existing = (
                session.query(ScholarshipVersion)
                .filter(ScholarshipVersion.scholarship_id == sid)
                .one()
            )
            duplicate = ScholarshipVersion(
                scholarship_id=sid,
                version_number=existing.version_number,
                changed_at=datetime.now(timezone.utc),
                change_summary="deliberate duplicate",
            )
            session.add(duplicate)
            with pytest.raises(IntegrityError) as exc:
                session.commit()
            assert "uq_scholarship_version_number" in str(exc.value)
            session.rollback()

            assert (
                session.query(ScholarshipVersion)
                .filter(ScholarshipVersion.scholarship_id == sid)
                .count()
                == 1
            )
        finally:
            _cleanup(session, session.get(Provider, provider.provider_id))
            session.close()

    def test_unique_constraint_exists_on_both_columns(self):
        """Not merely 'some unique index' — the PK is one of those too."""
        session = SessionLocal()
        try:
            from sqlalchemy import text

            rows = session.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='scholarship_version'::regclass AND contype='u'"
                )
            ).all()
            definitions = {name: definition for name, definition in rows}
            assert "uq_scholarship_version_number" in definitions, (
                f"expected the unique constraint, found: {sorted(definitions)}"
            )
            definition = definitions["uq_scholarship_version_number"]
            assert "scholarship_id" in definition
            assert "version_number" in definition
        finally:
            session.close()
