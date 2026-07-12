"""Tests for ExplanationEngine (M3.5)."""

from datetime import date, timedelta

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.matching.explanation import ExplanationEngine
from services.matching.models.profile import UserProfile
from services.matching.scoring import ScoringEngine

pytestmark = pytest.mark.integration


@pytest.fixture
def db_session():
    return SessionLocal()


@pytest.fixture
def reference_data(db_session):
    country = db_session.query(Country).filter_by(name="Japan").first()
    provider = db_session.query(Provider).first()
    source = db_session.query(SourceRegistry).first()
    if not all([country, provider, source]):
        pytest.skip("Prerequisite seed data not found")
    return country, provider, source


@pytest.fixture
def engines():
    return ScoringEngine(), ExplanationEngine()


@pytest.fixture
def profile():
    return UserProfile(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science"],
        current_gpa=3.5,
        ielts_score=7.0,
        research_experience="Preferred",
        work_experience="Optional",
        publication="Not Required",
        leadership=True,
        funding_preference="Fully Funded",
    )


class TestExplanationEngine:
    """ExplanationEngine deterministic explanation tests."""

    def test_good_match_has_strengths(self, db_session, reference_data, engines, profile):
        country, provider, source = reference_data
        scoring, explanation = engines

        sch = Scholarship(
            scholarship_name="Good Match",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        sch.requirement = ScholarshipRequirement(minimum_gpa=3.0, ielts_required=True, minimum_ielts=6.5)
        sch.timeline = ScholarshipTimeline(application_deadline=date.today() + timedelta(days=90))
        db_session.add(sch)
        db_session.commit()

        scores = scoring.score(profile, sch)
        result = explanation.explain(profile, sch, scores)

        assert scores.total >= 80
        assert len(result.strengths) > 0
        assert "Excellent" in result.summary or "Strong" in result.summary

        db_session.delete(sch)
        db_session.commit()

    def test_poor_match_has_gaps(self, db_session, reference_data, engines, profile):
        country, provider, source = reference_data
        scoring, explanation = engines

        sch = Scholarship(
            scholarship_name="Poor Match",
            degree="Bachelor",
            funding_type="Tuition Only",
            field_of_study=["Medicine"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        sch.requirement = ScholarshipRequirement(minimum_gpa=3.8, ielts_required=True, minimum_ielts=8.0)
        sch.timeline = ScholarshipTimeline(application_deadline=date.today() + timedelta(days=30))
        db_session.add(sch)
        db_session.commit()

        scores = scoring.score(profile, sch)
        result = explanation.explain(profile, sch, scores)

        assert len(result.gaps) > 0
        assert "Low" in result.summary or "Moderate" in result.summary

        db_session.delete(sch)
        db_session.commit()

    def test_next_steps_include_url(self, db_session, reference_data, engines, profile):
        country, provider, source = reference_data
        scoring, explanation = engines

        sch = Scholarship(
            scholarship_name="URL Test",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science"],
            official_page_url="https://example.com/test",
            application_url="https://example.com/apply",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        db_session.add(sch)
        db_session.commit()

        scores = scoring.score(profile, sch)
        result = explanation.explain(profile, sch, scores)

        has_url = any("example.com" in step for step in result.next_steps)
        assert has_url

        db_session.delete(sch)
        db_session.commit()
