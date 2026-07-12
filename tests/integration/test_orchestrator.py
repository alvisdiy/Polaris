"""Tests for ScholarshipIntelligenceEngine orchestrator (M3.6)."""

from datetime import date, timedelta

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.matching.models.profile import UserProfile
from services.matching.orchestrator import ScholarshipIntelligenceEngine

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


@pytest.fixture
def seed_scholarships(db_session, reference_data):
    country, provider, source = reference_data

    sch_a = Scholarship(
        scholarship_name="MEXT Scholarship",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Computer Science"],
        official_page_url="https://example.com/mext",
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        extraction_status="approved",
    )
    sch_a.requirement = ScholarshipRequirement(
        minimum_gpa=3.0,
        ielts_required=True,
        minimum_ielts=6.5,
        research_experience="Preferred",
        work_experience="Optional",
    )
    sch_a.timeline = ScholarshipTimeline(application_deadline=date.today() + timedelta(days=90))

    sch_b = Scholarship(
        scholarship_name="Expired Scholarship",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Computer Science"],
        official_page_url="https://example.com/expired",
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        extraction_status="approved",
    )
    sch_b.timeline = ScholarshipTimeline(application_deadline=date.today() - timedelta(days=30))

    db_session.add_all([sch_a, sch_b])
    db_session.commit()
    ids = [sch_a.scholarship_id, sch_b.scholarship_id]

    from sqlalchemy.orm import joinedload

    scholarships = (
        db_session.query(Scholarship)
        .options(
            joinedload(Scholarship.country),
            joinedload(Scholarship.requirement),
            joinedload(Scholarship.benefit),
            joinedload(Scholarship.timeline),
        )
        .filter(Scholarship.scholarship_id.in_(ids))
        .all()
    )

    yield scholarships

    for sid in ids:
        s = db_session.query(Scholarship).filter_by(scholarship_id=sid).first()
        if s:
            db_session.delete(s)
    db_session.commit()


class TestOrchestrator:
    """Full pipeline integration tests."""

    def test_expired_filtered_out(self, profile, seed_scholarships):
        engine = ScholarshipIntelligenceEngine()
        results = engine.match(profile, seed_scholarships)
        names = {r.scholarship_name for r in results}
        assert "Expired Scholarship" not in names

    def test_results_sorted_by_score(self, profile, seed_scholarships):
        engine = ScholarshipIntelligenceEngine()
        results = engine.match(profile, seed_scholarships)
        scores = [r.match_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_mext_ranks_first(self, profile, seed_scholarships):
        engine = ScholarshipIntelligenceEngine()
        results = engine.match(profile, seed_scholarships)
        assert len(results) >= 1
        assert results[0].scholarship_name == "MEXT Scholarship"

    def test_top_n_truncation(self, profile, seed_scholarships):
        from services.matching.ranking import RankingEngine

        engine = ScholarshipIntelligenceEngine(ranking_engine=RankingEngine(top_n=1))
        results = engine.match(profile, seed_scholarships)
        assert len(results) == 1

    def test_results_have_explanations(self, profile, seed_scholarships):
        engine = ScholarshipIntelligenceEngine()
        results = engine.match(profile, seed_scholarships)
        for r in results:
            assert isinstance(r.strengths, list)
