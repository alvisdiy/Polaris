"""Tests for POST /recommendations endpoint."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def seed_scholarship():
    """Seed a test scholarship for API tests."""
    session = SessionLocal()
    country = session.query(Country).filter_by(name="Japan").first()
    provider = session.query(Provider).first()
    source = session.query(SourceRegistry).first()

    if not all([country, provider, source]):
        pytest.skip("Prerequisite seed data not found")

    sch = Scholarship(
        scholarship_name="MEXT Scholarship (Test)",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Computer Science"],
        official_page_url="https://example.com/mext",
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        extraction_status="approved",
    )
    sch.requirement = ScholarshipRequirement(
        minimum_gpa=3.0,
        ielts_required=True,
        minimum_ielts=6.5,
    )
    sch.timeline = ScholarshipTimeline(
        application_deadline=date.today() + timedelta(days=90),
    )
    session.add(sch)
    session.commit()
    session.refresh(sch)
    sid = sch.scholarship_id

    yield sid

    # Cleanup
    s = session.query(Scholarship).filter_by(scholarship_id=sid).first()
    if s:
        session.delete(s)
        session.commit()
    session.close()


class TestRecommendationsEndpoint:
    """Tests for POST /recommendations."""

    def test_returns_200(self, client, sample_request):
        """Valid request returns HTTP 200."""
        response = client.post("/recommendations", json=sample_request)
        assert response.status_code == 200

    def test_versioned_matching_contract(self, client, sample_request):
        """The intended versioned endpoint returns traceable results."""
        response = client.post("/api/v1/matching", json=sample_request)
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["scholarship_id"]
        assert "deadline" in result

    def test_response_has_results_and_total(self, client, sample_request):
        """Response contains 'results' list and 'total' integer."""
        data = client.post("/recommendations", json=sample_request).json()
        assert "results" in data
        assert "total" in data
        assert isinstance(data["results"], list)
        assert isinstance(data["total"], int)

    def test_at_least_one_result(self, client, sample_request):
        """At least one recommendation returned when scholarships exist."""
        data = client.post("/recommendations", json=sample_request).json()
        assert data["total"] >= 1

    def test_result_schema(self, client, sample_request):
        """Each result has all required fields with correct types."""
        data = client.post("/recommendations", json=sample_request).json()
        result = data["results"][0]

        assert isinstance(result["scholarship_name"], str)
        assert isinstance(result["provider_name"], str)
        assert isinstance(result["country"], str)
        assert isinstance(result["match_score"], (int, float))
        assert isinstance(result["recommendation_category"], str)
        assert isinstance(result["explanation"], str)
        assert isinstance(result["strengths"], list)
        assert isinstance(result["gaps"], list)
        assert isinstance(result["next_steps"], list)
        assert isinstance(result["official_url"], str)

    def test_match_score_range(self, client, sample_request):
        """Match score is between 0 and 100."""
        data = client.post("/recommendations", json=sample_request).json()
        for result in data["results"]:
            assert 0 <= result["match_score"] <= 100

    def test_recommendation_category_valid(self, client, sample_request):
        """Recommendation category is one of the valid values."""
        valid_categories = {"Excellent Match", "Strong Match", "Good Match", "Moderate Match", "Low Match"}
        data = client.post("/recommendations", json=sample_request).json()
        for result in data["results"]:
            assert result["recommendation_category"] in valid_categories

    def test_results_sorted_by_score(self, client, sample_request):
        """Results are sorted by match_score descending."""
        data = client.post("/recommendations", json=sample_request).json()
        scores = [r["match_score"] for r in data["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_explanation_not_empty(self, client, sample_request):
        """Explanation field is non-empty for scored results."""
        data = client.post("/recommendations", json=sample_request).json()
        for result in data["results"]:
            assert result["explanation"]

    def test_validation_error_empty_fields(self, client):
        """Empty field_of_study returns 422."""
        payload = {
            "target_country": "Japan",
            "degree": "Master",
            "field_of_study": [],
            "current_gpa": 3.5,
            "research_experience": "Optional",
            "work_experience": "Optional",
            "publication": "Not Required",
            "leadership": False,
            "funding_preference": "Fully Funded",
        }
        response = client.post("/recommendations", json=payload)
        assert response.status_code == 422

    def test_validation_error_gpa_out_of_range(self, client):
        """GPA > 4.0 returns 422."""
        payload = {
            "target_country": "Japan",
            "degree": "Master",
            "field_of_study": ["CS"],
            "current_gpa": 5.0,
            "research_experience": "Optional",
            "work_experience": "Optional",
            "publication": "Not Required",
            "leadership": False,
            "funding_preference": "Fully Funded",
        }
        response = client.post("/recommendations", json=payload)
        assert response.status_code == 422

    def test_validation_error_missing_field(self, client):
        """Missing required field returns 422."""
        payload = {
            "target_country": "Japan",
            # missing degree
            "field_of_study": ["CS"],
            "current_gpa": 3.5,
            "research_experience": "Optional",
            "work_experience": "Optional",
            "publication": "Not Required",
            "leadership": False,
            "funding_preference": "Fully Funded",
        }
        response = client.post("/recommendations", json=payload)
        assert response.status_code == 422


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok(self, client):
        data = client.get("/health").json()
        assert data == {"status": "ok"}
