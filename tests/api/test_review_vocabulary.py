"""API tests: what a reviewer is told when they enter a bad category.

M9.1 Phase 4, Phase 8. Before this phase a reviewer could PATCH
``degree="Polytechnic"`` and receive 200 with the value stored. Now the request
must fail with a message that names the field, the refused value, the allowed
values, and whether null is acceptable — enough to fix the edit without reading
the source code.

The error is 422, not 409: the request was well formed and the record is in a
perfectly reviewable state. The reviewer's own input was wrong, and telling
them to reload and retry would send them in the wrong direction.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.exploration.acquisition_service import AcquisitionService
from services.review import ReviewService

TEST_NAME = "M91 API Vocabulary Scholarship"
TEST_PROVIDER = "M91 API Vocabulary Foundation"


@pytest.fixture
def record(client):
    """A published record, committed for real and removed afterwards."""
    setup = SessionLocal()
    try:
        jp = setup.query(Country).filter(Country.iso2 == "JP").first()
        provider = setup.query(Provider).filter(Provider.provider_code == "M91_APIV").first()
        if provider is None:
            provider = Provider(
                provider_code="M91_APIV",
                provider_name=TEST_PROVIDER,
                provider_type="Foundation",
                country_id=jp.country_id,
                verification_status="verified",
            )
            setup.add(provider)
            setup.flush()
        source = (
            setup.query(SourceRegistry)
            .filter(SourceRegistry.official_url == "https://m91-apiv.ac.uk/scholarship")
            .first()
        )
        if source is None:
            source = SourceRegistry(
                source_name="M91 API Vocabulary Source",
                country_id=jp.country_id,
                provider_id=provider.provider_id,
                official_url="https://m91-apiv.ac.uk/scholarship",
                crawl_entry_url="https://m91-apiv.ac.uk/",
                crawl_method="HTTP",
                crawl_frequency="monthly",
                status="Active",
            )
            setup.add(source)
            setup.flush()

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
            raw_content="m91 api vocabulary test page",
            checksum=hashlib.sha256(uuid.uuid4().hex.encode()).hexdigest(),
            fetched_at=datetime.now(timezone.utc),
        )
        setup.add(doc)
        setup.flush()
        extracted = ExtractedScholarship(
            scholarship_name=TEST_NAME,
            provider_name=TEST_PROVIDER,
            country=None,
            degree="Master",
            field_of_study=["Computer Science"],
            application_url="https://m91-apiv.ac.uk/apply",
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
        saved = AcquisitionService(setup)._persist_with_dedup(
            result, str(doc.document_id)
        )
        ReviewService(setup).approve(
            str(saved.scholarship_id), actor="setup", reason="initial publication"
        )
        setup.commit()
        yield str(saved.scholarship_id), provider.provider_id, source.source_id
    finally:
        _cleanup(setup)
        setup.close()


def _cleanup(session):
    provider = session.query(Provider).filter(Provider.provider_code == "M91_APIV").first()
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
            RawDocument.raw_content == "m91 api vocabulary test page",
        ).delete(synchronize_session=False)
    session.commit()


class TestReviewerVocabularyErrors:
    def test_polytechnic_is_refused_with_422(self, client, record):
        sid, _, _ = record
        response = client.patch(
            f"/api/v1/admin/review/scholarships/{sid}",
            json={
                "actor": "alice",
                "reason": "setting the degree",
                "changes": {"degree": "Polytechnic"},
                "requeue": False,
            },
        )
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert "Polytechnic" in detail
        assert "degree" in detail

    def test_error_lists_allowed_values_and_nullability(self, client, record):
        sid, _, _ = record
        response = client.patch(
            f"/api/v1/admin/review/scholarships/{sid}",
            json={
                "actor": "alice",
                "reason": "setting the degree",
                "changes": {"degree": "Diploma"},
                "requeue": False,
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        for value in ("Bachelor", "Exchange", "Master", "PhD", "Short Course"):
            assert value in detail, f"{value} missing from the error message"
        assert "left empty" in detail

    def test_valid_degree_is_accepted(self, client, record):
        sid, _, _ = record
        response = client.patch(
            f"/api/v1/admin/review/scholarships/{sid}",
            json={
                "actor": "alice",
                "reason": "official page states PhD",
                "changes": {"degree": "PhD"},
                "requeue": False,
            },
        )
        assert response.status_code == 200, response.text

        check = SessionLocal()
        try:
            assert check.get(Scholarship, sid).degree == "PhD"
        finally:
            check.close()

    def test_clearing_the_degree_is_accepted(self, client, record):
        """NULL is a legitimate answer, not a validation failure."""
        sid, _, _ = record
        response = client.patch(
            f"/api/v1/admin/review/scholarships/{sid}",
            json={
                "actor": "alice",
                "reason": "source states a diploma, which is not a degree level",
                "changes": {"degree": None},
                "requeue": False,
            },
        )
        assert response.status_code == 200, response.text

        check = SessionLocal()
        try:
            assert check.get(Scholarship, sid).degree is None
        finally:
            check.close()

    def test_refused_edit_does_not_change_anything(self, client, record):
        sid, _, _ = record
        before = SessionLocal()
        try:
            row = before.get(Scholarship, sid)
            original_degree = row.degree
            original_cycle = row.timeline.application_cycle
        finally:
            before.close()

        response = client.patch(
            f"/api/v1/admin/review/scholarships/{sid}",
            json={
                "actor": "alice",
                "reason": "one good, one bad",
                "changes": {"application_cycle": "2028-cycle", "degree": "Polytechnic"},
                "requeue": False,
            },
        )
        assert response.status_code == 422

        after = SessionLocal()
        try:
            row = after.get(Scholarship, sid)
            assert row.degree == original_degree
            assert row.timeline.application_cycle == original_cycle
        finally:
            after.close()

    def test_invalid_funding_type_is_refused_with_422(self, client, record):
        sid, _, _ = record
        response = client.patch(
            f"/api/v1/admin/review/scholarships/{sid}",
            json={
                "actor": "alice",
                "reason": "funding",
                "changes": {"funding_type": "Free Money"},
                "requeue": False,
            },
        )
        assert response.status_code == 422
        assert "Free Money" in response.json()["detail"]

    def test_unknown_field_is_still_a_409_not_a_422(self, client, record):
        """An unknown field is a different failure and keeps its status code."""
        sid, _, _ = record
        response = client.patch(
            f"/api/v1/admin/review/scholarships/{sid}",
            json={
                "actor": "alice",
                "reason": "typo",
                "changes": {"not_a_field": "x"},
                "requeue": False,
            },
        )
        assert response.status_code == 409
