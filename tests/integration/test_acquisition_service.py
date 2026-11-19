"""Integration tests: AcquisitionService persistence (identity dedup path).

Regression coverage for the first live zero-seed JP run, where every
acquisition attempt died with ``NameError: ScholarshipMapperWithIdentity``
before a single scholarship could be persisted.
"""

import hashlib
from datetime import datetime, timezone

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.source_registry import SourceRegistry
from services.exploration.acquisition_service import (
    AcquisitionService,
    scholarship_identity_key,
)
from services.ingestion.extractor import ExtractedDocument, ExtractedScholarship
from services.ingestion.orchestrator import PipelineResult
from services.ingestion.validator import ValidationReport


@pytest.fixture
def session(rollback_session):
    return rollback_session


@pytest.fixture
def jp_country(session):
    return session.query(Country).filter(Country.iso2 == "JP").first()


@pytest.fixture
def seeded_provider_and_source(session, jp_country):
    provider = Provider(
        provider_code="XYZ_FOUNDATION",
        provider_name="XYZ Foundation",
        provider_type="Foundation",
        country_id=jp_country.country_id,
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name="XYZ Foundation Official Site",
        country_id=jp_country.country_id,
        provider_id=provider.provider_id,
        official_url="https://xyz.example.org/scholarship",
        crawl_entry_url="https://xyz.example.org/",
        crawl_method="HTTP",
        crawl_frequency="monthly",
        status="Active",
    )
    session.add_all([provider, source])
    session.flush()
    return provider, source


def _raw_document(session, source, checksum_seed: str) -> RawDocument:
    doc = RawDocument(
        source_id=source.source_id,
        source_url="https://xyz.example.org/scholarship",
        content_type="text/html",
        raw_content="<html><body>scholarship page</body></html>",
        checksum=hashlib.sha256(checksum_seed.encode()).hexdigest(),
        fetched_at=datetime.now(timezone.utc),
    )
    session.add(doc)
    session.flush()
    return doc


def _pipeline_result(document_id: str) -> PipelineResult:
    extracted = ExtractedScholarship(
        scholarship_name="XYZ Foundation Scholarship 2026",
        provider_name="XYZ Foundation",
        country=None,  # falls back to the source's country
        application_url="https://xyz.example.org/apply",
        official_source="https://xyz.example.org/scholarship",
    )
    return PipelineResult(
        document_id=document_id,
        source_url="https://xyz.example.org/scholarship",
        is_valid=True,
        extracted_data=extracted.model_dump(),
        validation_report=ValidationReport(is_valid=True, issues=[]),
        raw_extraction=ExtractedDocument(
            document_id=document_id,
            source_url="https://xyz.example.org/scholarship",
            scholarship=extracted,
        ),
    )


class TestPersistWithDedup:
    def test_valid_extraction_is_persisted(self, session, seeded_provider_and_source, jp_country):
        provider, source = seeded_provider_and_source
        doc = _raw_document(session, source, "doc-1")
        service = AcquisitionService(session)

        scholarship = service._persist_with_dedup(_pipeline_result(str(doc.document_id)), str(doc.document_id))

        assert scholarship is not None
        assert scholarship.scholarship_name == "XYZ Foundation Scholarship 2026"
        assert scholarship.provider_id == provider.provider_id
        assert scholarship.country_id == jp_country.country_id
        assert scholarship.identity_key == scholarship_identity_key(
            scholarship.provider_id, scholarship.scholarship_name, scholarship.country_id
        )

    def test_second_extraction_with_same_identity_collapses(self, session, seeded_provider_and_source):
        _, source = seeded_provider_and_source
        doc1 = _raw_document(session, source, "doc-1")
        doc2 = _raw_document(session, source, "doc-2")
        service = AcquisitionService(session)

        first = service._persist_with_dedup(_pipeline_result(str(doc1.document_id)), str(doc1.document_id))
        second = service._persist_with_dedup(_pipeline_result(str(doc2.document_id)), str(doc2.document_id))

        assert first is not None
        assert second is None  # one canonical row per identity_key
