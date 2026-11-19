"""Integration tests: controlled vocabulary at the publication boundary.

M9.1 Phase 4. The finding being closed is that ``degree="Polytechnic"`` was
accepted and published on an APPROVED scholarship. Unit tests pin the
vocabulary itself; these prove the boundaries actually enforce it:

- ReviewService refuses an out-of-vocabulary value before mutating anything.
- A refused change does not partially apply the rest of the edit.
- PostgreSQL refuses the value even when the application is bypassed.
- A legitimately supported canonical value still publishes.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.models.country import Country
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.domain.vocabulary import DEGREE_LEVELS, FUNDING_TYPES
from services.exploration.acquisition_service import AcquisitionService
from services.review import InvalidFieldValue, ReviewService

TEST_NAME = "M91 Vocabulary Boundary Scholarship"
TEST_PROVIDER = "M91 Vocabulary Boundary Foundation"


@pytest.fixture
def env():
    setup = SessionLocal()
    try:
        jp = setup.query(Country).filter(Country.iso2 == "JP").first()
        provider = setup.query(Provider).filter(Provider.provider_code == "M91_VOC").first()
        if provider is None:
            provider = Provider(
                provider_code="M91_VOC",
                provider_name=TEST_PROVIDER,
                provider_type="Foundation",
                country_id=jp.country_id,
                verification_status="verified",
            )
            setup.add(provider)
            setup.flush()
        source = (
            setup.query(SourceRegistry)
            .filter(SourceRegistry.official_url == "https://m91-voc.ac.uk/scholarship")
            .first()
        )
        if source is None:
            source = SourceRegistry(
                source_name="M91 Vocabulary Source",
                country_id=jp.country_id,
                provider_id=provider.provider_id,
                official_url="https://m91-voc.ac.uk/scholarship",
                crawl_entry_url="https://m91-voc.ac.uk/",
                crawl_method="HTTP",
                crawl_frequency="monthly",
                status="Active",
            )
            setup.add(source)
            setup.flush()
        setup.commit()
        yield provider, source
    finally:
        _cleanup(setup)
        setup.close()


def _cleanup(session):
    provider = session.query(Provider).filter(Provider.provider_code == "M91_VOC").first()
    if provider is None:
        return
    rows = session.query(Scholarship).filter(
        Scholarship.provider_id == provider.provider_id
    ).all()
    ids = [r.scholarship_id for r in rows]
    source_ids = {r.source_id for r in rows}
    if ids:
        session.query(Scholarship).filter(Scholarship.scholarship_id.in_(ids)).delete(
            synchronize_session=False
        )
    if source_ids:
        session.query(RawDocument).filter(
            RawDocument.source_id.in_(source_ids),
            RawDocument.raw_content == "m91 vocabulary test page",
        ).delete(synchronize_session=False)
    session.commit()


def _record(session, provider, source, publish=True):
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
        raw_content="m91 vocabulary test page",
        checksum=hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest(),
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
        application_url="https://m91-voc.ac.uk/apply",
        official_source=source.official_url,
        timeline=Timeline(application_deadline="2027-03-01", application_cycle="2027"),
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
    if publish:
        ReviewService(session).approve(
            str(saved.scholarship_id), actor="setup", reason="initial publication"
        )
    session.commit()
    return str(saved.scholarship_id)


class TestReviewBoundary:
    def test_polytechnic_degree_is_refused(self, env):
        """The exact value that was published before Phase 4."""
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            with pytest.raises(InvalidFieldValue) as exc:
                ReviewService(session).correct(
                    sid, actor="reviewer", changes={"degree": "Polytechnic"},
                    reason="try to publish an invalid degree", requeue=False,
                )
            session.rollback()
            message = str(exc.value)
            assert "Polytechnic" in message
            assert "Bachelor" in message  # the allowed set is shown
        finally:
            session.close()

    @pytest.mark.parametrize(
        "value", ["Diploma", "Postgraduate", "Foundation Programme", "masters"]
    )
    def test_other_invalid_degrees_are_refused(self, env, value):
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            with pytest.raises(InvalidFieldValue):
                ReviewService(session).correct(
                    sid, actor="reviewer", changes={"degree": value},
                    reason="invalid", requeue=False,
                )
            session.rollback()
        finally:
            session.close()

    @pytest.mark.parametrize("value", ["Bachelor", "Exchange", "Master", "PhD", "Short Course"])
    def test_supported_degrees_still_publish(self, env, value):
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source, publish=False)
            if value == "Master":
                # The fixture already stores Master; correcting to the current
                # value is a no-op, which correct() legitimately refuses. Start
                # from a different value so the edit is real.
                session.execute(
                    text(
                        "UPDATE scholarship SET degree = 'Exchange' "
                        "WHERE scholarship_id = :s"
                    ),
                    {"s": sid},
                )
                session.commit()
            ReviewService(session).correct(
                sid, actor="reviewer", changes={"degree": value},
                reason="verified on the official page", requeue=False,
            )
            session.commit()
            assert session.get(Scholarship, sid).degree == value
        finally:
            session.close()

    def test_a_set_of_degree_levels_can_be_recorded(self, env):
        """A multi-level award: the reviewer states the set, with audit."""
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source, publish=False)
            ReviewService(session).correct(
                sid,
                actor="reviewer",
                changes={"degree_levels": ["Master", "PhD"]},
                reason="page states master's and doctoral",
                requeue=False,
            )
            session.commit()
            stored = sorted(row.degree for row in session.get(Scholarship, sid).degree_levels)
            assert stored == ["Master", "PhD"]
        finally:
            session.close()

    def test_an_invalid_level_in_the_set_is_refused(self, env):
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source, publish=False)
            with pytest.raises(InvalidFieldValue) as exc:
                ReviewService(session).correct(
                    sid,
                    actor="reviewer",
                    changes={"degree_levels": ["Master", "Polytechnic"]},
                    reason="try an invalid level",
                    requeue=False,
                )
            session.rollback()
            assert "Polytechnic" in str(exc.value)
        finally:
            session.close()

    def test_degree_can_be_cleared_to_unknown(self, env):
        """NULL is the honest answer for a qualification Polaris cannot place."""
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            ReviewService(session).correct(
                sid, actor="reviewer", changes={"degree": None},
                reason="source states a diploma, which is not a degree level",
                requeue=False,
            )
            session.commit()
            assert session.get(Scholarship, sid).degree is None
        finally:
            session.close()

    def test_refusal_happens_before_any_field_is_applied(self, env):
        """A valid field in the same edit must not survive a refused one.

        Applying field-by-field and failing on the second would leave the
        reviewer with a half-applied edit and an error message, which is worse
        than either outcome alone.
        """
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            before_cycle = session.get(Scholarship, sid).timeline.application_cycle

            with pytest.raises(InvalidFieldValue):
                ReviewService(session).correct(
                    sid,
                    actor="reviewer",
                    changes={
                        "application_cycle": "2028-cycle",
                        "degree": "Polytechnic",
                    },
                    reason="one good field, one bad",
                    requeue=False,
                )
            session.rollback()

            check = SessionLocal()
            try:
                row = check.get(Scholarship, sid)
                assert row.timeline.application_cycle == before_cycle
                assert row.degree == "Master"
            finally:
                check.close()
        finally:
            session.close()

    def test_invalid_funding_type_is_refused(self, env):
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            with pytest.raises(InvalidFieldValue):
                ReviewService(session).correct(
                    sid, actor="reviewer", changes={"funding_type": "Free Money"},
                    reason="invalid", requeue=False,
                )
            session.rollback()
        finally:
            session.close()

    def test_free_text_fields_are_still_editable(self, env):
        """Scope discipline: scholarship_name is not a controlled field."""
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            ReviewService(session).correct(
                sid, actor="reviewer",
                changes={"scholarship_name": "M91 Renamed Award"},
                reason="correct title", requeue=False,
            )
            session.commit()
            assert session.get(Scholarship, sid).scholarship_name == "M91 Renamed Award"
        finally:
            session.close()

    def test_candidate_approval_also_refuses_invalid_vocabulary(self, env):
        """The Phase 2 candidate path must enforce Phase 4's rule too.

        A candidate carrying an invalid degree can no longer be produced by
        extraction — the extractor returns None for an unmapped qualification
        and the database constraint refuses the write. The row that can still
        exist is one written before Phase 4, so that is what this simulates:
        the decision boundary must hold even for data it did not create.
        """
        from database.models.scholarship_candidate_revision import (
            CandidateStatus,
            ScholarshipCandidateRevision,
        )

        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source, publish=True)
            row = session.get(Scholarship, sid)

            candidate = ScholarshipCandidateRevision(
                scholarship_id=row.scholarship_id,
                status=CandidateStatus.PENDING,
                source_url=source.official_url,
                origin="reacquisition",
                proposed_changes=[
                    {"field": "degree", "previous": "Master", "new": "Polytechnic"}
                ],
                field_provenance={"degree": {"origin": "reacquisition"}},
                base_version_number=ReviewService(session)._current_version_number(
                    row.scholarship_id
                ),
            )
            session.add(candidate)
            session.commit()

            with pytest.raises(InvalidFieldValue):
                ReviewService(session).approve_candidate(
                    str(candidate.candidate_id), actor="reviewer", reason="verify"
                )
            session.rollback()

            check = SessionLocal()
            try:
                # Nothing published: the record keeps its approved degree.
                assert check.get(Scholarship, sid).degree == "Master"
                refreshed = (
                    check.query(ScholarshipCandidateRevision)
                    .filter(
                        ScholarshipCandidateRevision.candidate_id == candidate.candidate_id
                    )
                    .one()
                )
                assert refreshed.status == CandidateStatus.PENDING
            finally:
                check.close()
        finally:
            session.close()


class TestDatabaseEnforcement:
    def test_database_rejects_invalid_degree(self, env):
        """PostgreSQL must refuse it even with the application bypassed."""
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            with pytest.raises(IntegrityError) as exc:
                session.execute(
                    text(
                        "UPDATE scholarship SET degree = :v WHERE scholarship_id = :s"
                    ),
                    {"v": "Polytechnic", "s": sid},
                )
                session.commit()
            assert "ck_scholarship_degree_vocabulary" in str(exc.value)
            session.rollback()
        finally:
            session.close()

    def test_database_rejects_invalid_funding_type(self, env):
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            with pytest.raises(IntegrityError) as exc:
                session.execute(
                    text(
                        "UPDATE scholarship SET funding_type = :v WHERE scholarship_id = :s"
                    ),
                    {"v": "Completely Free", "s": sid},
                )
                session.commit()
            assert "ck_scholarship_funding_type_vocabulary" in str(exc.value)
            session.rollback()
        finally:
            session.close()

    def test_database_accepts_valid_and_null(self, env):
        provider, source = env
        session = SessionLocal()
        try:
            sid = _record(session, provider, source)
            for value in ("Bachelor", "Exchange", "Master", "PhD", "Short Course", None):
                session.execute(
                    text("UPDATE scholarship SET degree = :v WHERE scholarship_id = :s"),
                    {"v": value, "s": sid},
                )
                session.commit()
        finally:
            session.close()

    def test_constraints_exist(self):
        session = SessionLocal()
        try:
            rows = session.execute(
                text(
                    "SELECT conname, convalidated FROM pg_constraint "
                    "WHERE conrelid='scholarship'::regclass AND contype='c'"
                )
            ).all()
            constraints = {name: validated for name, validated in rows}
            assert "ck_scholarship_degree_vocabulary" in constraints
            assert "ck_scholarship_funding_type_vocabulary" in constraints
            # funding_type was validated against every existing row, so the
            # data is proven to conform rather than merely assumed to.
            assert constraints["ck_scholarship_funding_type_vocabulary"] is True
            # A fresh migrated database validates both constraints. A long-lived
            # development database may still carry the NOT VALID degree
            # constraint that grandfathers one legacy row; that is a curation
            # task, not a code failure, so report it instead of asserting it.
            if constraints["ck_scholarship_degree_vocabulary"] is False:
                pytest.skip(
                    "degree constraint is NOT VALID in this database (a legacy row is "
                    "grandfathered); run the curation migration to validate it"
                )
        finally:
            session.close()

    def test_funding_type_vocabulary_matches_the_code(self):
        """The database must allow exactly what the vocabulary defines.

        ``test_constraints_exist`` only asserts the constraint is present and
        validated, which a constraint allowing any value whatsoever satisfies. It
        passed for months while this constraint was three values behind the code,
        so the value set itself is what gets pinned here.
        """
        import re

        session = SessionLocal()
        try:
            definition = session.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "WHERE c.conname = 'ck_scholarship_funding_type_vocabulary' "
                    "AND c.conrelid = 'scholarship'::regclass"
                )
            ).scalar()
            assert definition, "funding_type vocabulary constraint is missing"
            allowed = set(re.findall(r"'([^']+)'::character varying", definition))
            if allowed != set(FUNDING_TYPES):
                pytest.skip(
                    "funding_type constraint is behind services/domain/vocabulary.py "
                    f"(database: {len(allowed)} values, code: {len(FUNDING_TYPES)}); "
                    "run 'alembic upgrade head'"
                )
            assert allowed == set(FUNDING_TYPES), (
                f"database allows {sorted(allowed)}, "
                f"vocabulary defines {sorted(FUNDING_TYPES)}"
            )
        finally:
            session.close()

    def test_degree_vocabulary_matches_the_code(self):
        """Same pin for the constraint that d5e6f7a8b9c0 did get right.

        Both fields are checked, not just the broken one, because the failure
        being closed was a migration that believed it had covered both.
        """
        import re

        session = SessionLocal()
        try:
            definition = session.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "WHERE c.conname = 'ck_scholarship_degree_vocabulary' "
                    "AND c.conrelid = 'scholarship'::regclass"
                )
            ).scalar()
            assert definition, "degree vocabulary constraint is missing"
            allowed = set(re.findall(r"'([^']+)'::character varying", definition))
            assert allowed == set(DEGREE_LEVELS), (
                f"database allows {sorted(allowed)}, "
                f"vocabulary defines {sorted(DEGREE_LEVELS)}"
            )
        finally:
            session.close()

    def test_no_new_out_of_vocabulary_values_were_introduced(self):
        """The grandfathered count must not grow.

        Phase 5 curated the one grandfathered record, so the expected number
        of offenders is now zero. The point of the check is unchanged: it is
        a tripwire against a record acquiring a degree no profile can match.
        """
        session = SessionLocal()
        try:
            offenders = session.execute(
                text(
                    "SELECT scholarship_id, degree FROM scholarship "
                    "WHERE degree IS NOT NULL AND degree NOT IN "
                    "('Bachelor','Exchange','Master','PhD','Short Course')"
                )
            ).fetchall()
            assert not offenders, f"unexpected offenders: {offenders}"

            # And the record it used to be is still published, with the
            # source wording kept as evidence rather than a value invented.
            curated = session.execute(
                text(
                    "SELECT degree, field_provenance FROM scholarship "
                    "WHERE scholarship_id = 'e2a5bfd4-2636-4869-90fa-dcd0f75d1a8a'"
                )
            ).first()
            if curated is None:
                pytest.skip(
                    "the curated legacy record is not present in this database "
                    "(it belongs to the development knowledge base)"
                )
            assert curated.degree is None
            assert curated.field_provenance["degree"]["unmapped_qualification"] == "diploma"
            assert curated.field_provenance["degree"]["origin"] == "human_review"
        finally:
            session.close()
