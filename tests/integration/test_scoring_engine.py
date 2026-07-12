"""Tests for ScoringEngine (M3.3)."""

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
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
def scoring_engine():
    return ScoringEngine()


@pytest.fixture
def perfect_profile():
    return UserProfile(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science", "Engineering"],
        current_gpa=3.8,
        ielts_score=7.5,
        research_experience="Preferred",
        work_experience="Optional",
        publication="Not Required",
        leadership=True,
        funding_preference="Fully Funded",
    )


class TestScoringEngine:
    """ScoringEngine weighted scoring tests."""

    def test_perfect_match_scores_100(self, db_session, reference_data, scoring_engine, perfect_profile):
        country, provider, source = reference_data
        sch = Scholarship(
            scholarship_name="Perfect Match",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science", "Engineering"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        sch.requirement = ScholarshipRequirement(
            minimum_gpa=3.0,
            ielts_required=True,
            minimum_ielts=6.5,
            research_experience="Preferred",
            work_experience="Optional",
        )
        db_session.add(sch)
        db_session.commit()

        scores = scoring_engine.score(perfect_profile, sch)
        assert scores.total == 100.0

        db_session.delete(sch)
        db_session.commit()

    def test_partial_field_overlap(self, db_session, reference_data, scoring_engine, perfect_profile):
        country, provider, source = reference_data
        sch = Scholarship(
            scholarship_name="Partial Field",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science", "Engineering"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        db_session.add(sch)
        db_session.commit()

        partial_profile = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["Computer Science"],
            current_gpa=3.8,
            ielts_score=7.5,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        scores = scoring_engine.score(partial_profile, sch)
        assert scores.field_of_study == 10.0

        db_session.delete(sch)
        db_session.commit()

    def test_gpa_below_minimum(self, db_session, reference_data, scoring_engine, perfect_profile):
        country, provider, source = reference_data
        sch = Scholarship(
            scholarship_name="GPA Test",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        sch.requirement = ScholarshipRequirement(minimum_gpa=3.0)
        db_session.add(sch)
        db_session.commit()

        low_gpa = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["Computer Science", "Engineering"],
            current_gpa=2.0,
            ielts_score=7.5,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        scores = scoring_engine.score(low_gpa, sch)
        assert scores.gpa == round(15.0 * (2.0 / 3.0), 2)

        db_session.delete(sch)
        db_session.commit()

    def test_language_miss(self, db_session, reference_data, scoring_engine):
        country, provider, source = reference_data
        sch = Scholarship(
            scholarship_name="Lang Test",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        sch.requirement = ScholarshipRequirement(ielts_required=True, minimum_ielts=6.5)
        db_session.add(sch)
        db_session.commit()

        no_ielts = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["Computer Science"],
            current_gpa=3.8,
            ielts_score=None,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        scores = scoring_engine.score(no_ielts, sch)
        assert scores.language == 0.0

        db_session.delete(sch)
        db_session.commit()

    def test_no_requirement_full_score(self, db_session, reference_data, scoring_engine):
        country, provider, source = reference_data
        sch = Scholarship(
            scholarship_name="No Req",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        db_session.add(sch)
        db_session.commit()

        minimal = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["Computer Science"],
            current_gpa=2.0,
            ielts_score=None,
            research_experience="Not Required",
            work_experience="Not Required",
            publication="Not Required",
            leadership=False,
            funding_preference="Fully Funded",
        )
        scores = scoring_engine.score(minimal, sch)
        assert scores.gpa == 15.0
        assert scores.language == 10.0
        assert scores.research == 5.0
        assert scores.work == 3.0

        db_session.delete(sch)
        db_session.commit()

    def test_country_mismatch(self, db_session, reference_data, scoring_engine, perfect_profile):
        country, provider, source = reference_data
        sch = Scholarship(
            scholarship_name="Country Test",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        db_session.add(sch)
        db_session.commit()

        wrong_country = UserProfile(
            target_country="Germany",
            degree="Master",
            field_of_study=["Computer Science", "Engineering"],
            current_gpa=3.8,
            ielts_score=7.5,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        scores = scoring_engine.score(wrong_country, sch)
        assert scores.country == 0.0

        db_session.delete(sch)
        db_session.commit()

    def test_research_one_level_below(self, db_session, reference_data, scoring_engine):
        country, provider, source = reference_data
        sch = Scholarship(
            scholarship_name="Research Test",
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Computer Science"],
            official_page_url="https://example.com",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            extraction_status="approved",
        )
        sch.requirement = ScholarshipRequirement(research_experience="Preferred")
        db_session.add(sch)
        db_session.commit()

        low_research = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["Computer Science"],
            current_gpa=3.8,
            ielts_score=7.5,
            research_experience="Optional",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        scores = scoring_engine.score(low_research, sch)
        assert scores.research == 2.5

        db_session.delete(sch)
        db_session.commit()
