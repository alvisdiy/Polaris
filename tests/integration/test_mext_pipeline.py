"""Integration test: MEXT connector → pipeline → scholarship persistence.

Uses a real HTML fixture and the MockLLMClient to verify the full
pipeline from raw HTML to persisted Scholarship.

Transaction isolation: each test runs inside a connection-level
transaction that is rolled back after the test, ensuring zero
cross-test contamination.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.source_registry import SourceRegistry
from database.session import get_engine, get_session_local
from services.ingestion.connectors.base_connector import FetchResult
from services.ingestion.mock_llm import MockLLMClient
from services.ingestion.orchestrator import persist_scholarship, run_pipeline
from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
from services.ingestion.repositories.raw_document_repository import RawDocumentRepository

pytestmark = pytest.mark.integration

# Realistic HTML fixture (simplified from actual studyinjapan.go.jp)
MEXT_HTML = """<!DOCTYPE html>
<html lang="en">
<head><title>Study in Japan - MEXT Scholarship</title></head>
<body>
<nav><a href="/">Home</a> | <a href="/scholarships">Scholarships</a></nav>
<main>
<h1>Japanese Government (MEXT) Scholarship Program</h1>
<p>The Ministry of Education, Culture, Sports, Science and Technology (MEXT)
offers scholarships to international students who wish to study at Japanese
universities under the Japanese Government Scholarship Program.</p>

<h2>Eligibility</h2>
<ul>
<li>Applicants must be under 35 years of age</li>
<li>Must have a GPA of 3.5 or above on a 4.0 scale</li>
<li>TOEFL score of 550 or above (paper-based)</li>
<li>Research experience is preferred</li>
<li>Recommendation letter required</li>
</ul>

<h2>Benefits</h2>
<ul>
<li>Tuition fees fully covered</li>
<li>Monthly allowance of 144,000 yen</li>
<li>Round-trip airfare</li>
<li>Health insurance</li>
</ul>

<h2>Application Period</h2>
<p>Applications open: April 1, 2026</p>
<p>Application deadline: May 31, 2026</p>
<p>Study start: April 2027</p>

<h2>How to Apply</h2>
<p>Apply through the Embassy of Japan in your country or through
the university recommendation route.</p>
<p><a href="https://www.studyinjapan.go.jp/en/smap-stopj-applications-scholarships.html">
Apply Now</a></p>
</main>
<footer>Study in Japan - Official Portal</footer>
</body>
</html>"""


@pytest.fixture()
def db_connection():
    """Yield a connection inside a transaction; rollback after each test."""
    engine = get_engine()
    connection = engine.connect()
    transaction = connection.begin()
    yield connection
    transaction.rollback()
    connection.close()


@pytest.fixture()
def db_session(db_connection):
    """Session bound to the connection transaction.

    begin_nested() creates a SAVEPOINT so that session.commit() releases
    the savepoint instead of committing the outer transaction.
    """
    from sqlalchemy.orm import Session

    session = Session(bind=db_connection)
    session.begin_nested()
    yield session
    session.close()


@pytest.fixture()
def seed_mext_source(db_session):
    """Ensure MEXT source exists in Source Registry."""
    country = db_session.query(Country).filter_by(iso3="JPN").first()
    if not country:
        country = Country(iso2="JP", iso3="JPN", name="Japan")
        db_session.add(country)
        db_session.flush()

    provider = db_session.query(Provider).filter_by(provider_code="MEXT").first()
    if not provider:
        provider = Provider(
            provider_code="MEXT",
            provider_name="Ministry of Education, Culture, Sports, Science and Technology",
            provider_type="Government",
            country_id=country.country_id,
            official_url="https://www.mext.go.jp/en/",
        )
        db_session.add(provider)
        db_session.flush()

    source = db_session.query(SourceRegistry).filter_by(connector_name="mext_connector").first()
    if not source:
        source = SourceRegistry(
            source_name="Study in Japan",
            country_id=country.country_id,
            provider_id=provider.provider_id,
            official_url="https://www.studyinjapan.go.jp/",
            crawl_entry_url="https://www.studyinjapan.go.jp/en/",
            crawl_method="HTTP",
            connector_name="mext_connector",
            crawl_frequency="Monthly",
            priority=1,
            robots_allowed=True,
            requires_login=False,
            status="Active",
        )
        db_session.add(source)
        db_session.flush()

    return source


@pytest.fixture()
def fetch_result(seed_mext_source):
    """Create a FetchResult from the HTML fixture."""
    return FetchResult(
        source_id=seed_mext_source.source_id,
        raw_content=MEXT_HTML,
        content_type="html",
        final_url="https://www.studyinjapan.go.jp/en/",
        response_size=len(MEXT_HTML.encode("utf-8")),
        encoding="utf-8",
        status_code=200,
        etag=None,
        last_modified=None,
        crawl_duration_ms=250,
        crawl_time=datetime.now(timezone.utc),
        processing_time_ms=250.0,
        retry_count=0,
        headers={},
    )


@pytest.fixture()
def override_get_db(db_session, monkeypatch):
    """Patch SessionLocal in the recommendations module to use test session."""
    import api.routers.recommendations as mod

    monkeypatch.setattr(mod, "SessionLocal", lambda: db_session)
    yield


class TestMextConnectorPipeline:
    """End-to-end pipeline tests using real HTML fixture."""

    def test_raw_document_mapper_creates_entity(self, fetch_result, seed_mext_source):
        """RawDocumentMapper converts FetchResult to RawDocument ORM."""
        mapper = RawDocumentMapper()
        raw_doc = mapper.to_orm(fetch_result)

        assert raw_doc.source_id == seed_mext_source.source_id
        assert raw_doc.source_url == "https://www.studyinjapan.go.jp/en/"
        assert raw_doc.content_type == "html"
        assert raw_doc.processing_status == "pending"
        assert len(raw_doc.checksum) == 64  # SHA-256 hex

    def test_raw_document_repository_save(self, db_session, fetch_result, seed_mext_source):
        """RawDocument can be persisted and retrieved."""
        mapper = RawDocumentMapper()
        raw_doc = mapper.to_orm(fetch_result)

        repo = RawDocumentRepository(db_session)
        saved = repo.save(raw_doc)

        assert saved.document_id is not None
        retrieved = repo.get_by_id(saved.document_id)
        assert retrieved is not None
        assert retrieved.source_url == "https://www.studyinjapan.go.jp/en/"

    def test_raw_document_dedup_by_checksum(self, db_session, fetch_result, seed_mext_source):
        """Duplicate raw documents are detected by checksum."""
        mapper = RawDocumentMapper()
        raw_doc = mapper.to_orm(fetch_result)

        repo = RawDocumentRepository(db_session)
        saved = repo.save(raw_doc)

        # Same checksum should find existing
        duplicate = repo.get_by_source_and_checksum(seed_mext_source.source_id, raw_doc.checksum)
        assert duplicate is not None
        assert duplicate.document_id == saved.document_id

    def test_full_pipeline_produces_scholarship(self, db_session, fetch_result, seed_mext_source):
        """Full pipeline: fetch → RawDocument → clean → extract → validate → persist."""
        # 1. Store RawDocument
        mapper = RawDocumentMapper()
        raw_doc = mapper.to_orm(fetch_result)
        repo = RawDocumentRepository(db_session)
        saved = repo.save(raw_doc)
        document_id = str(saved.document_id)

        # 2. Run pipeline with mock LLM
        llm_client = MockLLMClient()
        result = run_pipeline(document_id, db_session, llm_client)

        assert result.is_valid, f"Validation failed: {result.validation_report.issues}"
        assert result.raw_extraction.scholarship is not None
        assert result.raw_extraction.scholarship.scholarship_name == "MEXT Scholarship 2027"

        # 3. Persist scholarship
        scholarship = persist_scholarship(result, document_id, db_session)

        assert scholarship is not None
        assert scholarship.scholarship_name == "MEXT Scholarship 2027"
        assert scholarship.degree == "Master"
        assert scholarship.funding_type == "Fully Funded"
        assert scholarship.extraction_status == "pending_review"
        assert scholarship.provider_id is not None
        assert scholarship.country_id is not None

    def test_pipeline_scholarship_has_children(self, db_session, fetch_result, seed_mext_source):
        """Persisted scholarship has requirement, benefit, and timeline."""
        mapper = RawDocumentMapper()
        raw_doc = mapper.to_orm(fetch_result)
        repo = RawDocumentRepository(db_session)
        saved = repo.save(raw_doc)

        llm_client = MockLLMClient()
        result = run_pipeline(str(saved.document_id), db_session, llm_client)
        scholarship = persist_scholarship(result, str(saved.document_id), db_session)

        assert scholarship is not None
        assert scholarship.requirement is not None
        assert scholarship.requirement.minimum_gpa == 3.5
        assert scholarship.requirement.toefl_required is True
        assert scholarship.requirement.minimum_toefl == 550

        assert scholarship.benefit is not None
        assert scholarship.benefit.tuition_fee is True
        assert scholarship.benefit.monthly_allowance is True
        assert scholarship.benefit.health_insurance is True

        assert scholarship.timeline is not None
        assert scholarship.timeline.application_open is not None
        assert scholarship.timeline.application_deadline is not None

    def test_pipeline_scholarship_appears_in_approved_query(self, db_session, fetch_result, seed_mext_source):
        """Persisted scholarship can be retrieved via ScholarshipRepository."""
        from services.scholarship import ScholarshipRepository

        mapper = RawDocumentMapper()
        raw_doc = mapper.to_orm(fetch_result)
        repo = RawDocumentRepository(db_session)
        saved = repo.save(raw_doc)

        llm_client = MockLLMClient()
        result = run_pipeline(str(saved.document_id), db_session, llm_client)
        scholarship = persist_scholarship(result, str(saved.document_id), db_session)

        assert scholarship is not None

        # Change status to approved for retrieval
        scholarship.extraction_status = "approved"
        db_session.flush()

        sch_repo = ScholarshipRepository(db_session)
        all_approved = sch_repo.get_all_approved()
        assert any(s.scholarship_id == scholarship.scholarship_id for s in all_approved)

    def test_recommendations_api_returns_pipeline_scholarship(
        self, db_session, fetch_result, seed_mext_source, override_get_db
    ):
        """POST /recommendations returns scholarship from the pipeline."""
        from fastapi.testclient import TestClient

        from api.app import app

        # 1. Run full pipeline
        mapper = RawDocumentMapper()
        raw_doc = mapper.to_orm(fetch_result)
        repo = RawDocumentRepository(db_session)
        saved = repo.save(raw_doc)

        llm_client = MockLLMClient()
        result = run_pipeline(str(saved.document_id), db_session, llm_client)
        scholarship = persist_scholarship(result, str(saved.document_id), db_session)

        # 2. Auto-approve
        scholarship.extraction_status = "approved"
        db_session.flush()

        # 3. Call API
        client = TestClient(app)
        response = client.post(
            "/recommendations",
            json={
                "target_country": "Japan",
                "degree": "Master",
                "field_of_study": ["Computer Science"],
                "current_gpa": 3.8,
                "ielts_score": 7.5,
                "research_experience": "Preferred",
                "work_experience": "Optional",
                "publication": "Not Required",
                "leadership": True,
                "funding_preference": "Fully Funded",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        results = data["results"]
        assert len(results) > 0

        # Verify MEXT scholarship is in results
        names = [r["scholarship_name"] for r in results]
        assert "MEXT Scholarship 2027" in names
