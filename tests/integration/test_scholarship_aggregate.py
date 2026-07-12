"""Tests for Scholarship aggregate persistence (M3.0)."""

from datetime import date

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_benefit import ScholarshipBenefit
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.source_registry import SourceRegistry
from database.session import SessionLocal
from services.ingestion.extractor import (
    Benefits,
    Eligibility,
    ExtractedScholarship,
    Timeline,
)
from services.scholarship import ScholarshipMapper, ScholarshipRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def db_session():
    return SessionLocal()


@pytest.fixture
def reference_data(db_session):
    country = db_session.query(Country).filter_by(name="Japan").first()
    provider = (
        db_session.query(Provider)
        .filter_by(provider_name="Ministry of Education, Culture, Sports, Science and Technology")
        .first()
    )
    source = db_session.query(SourceRegistry).filter_by(source_name="Study in Japan").first()
    if not all([country, provider, source]):
        pytest.skip("Prerequisite seed data not found")
    return country, provider, source


@pytest.fixture
def extracted_scholarship(reference_data):
    country, provider, source = reference_data
    return ExtractedScholarship(
        scholarship_name="MEXT Scholarship 2027 (Test)",
        provider_name=provider.provider_name,
        scholarship_type="Government",
        country=country.name,
        university=None,
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Engineering", "Natural Sciences"],
        application_url="https://example.com/apply",
        official_source="https://example.com",
        timeline=Timeline(
            application_open="2026-04-01",
            application_deadline="2026-05-31",
            interview_date=None,
            result_date=None,
            study_start="2027-04-01",
        ),
        eligibility=Eligibility(
            minimum_gpa=3.5,
            ielts_required=False,
            minimum_ielts=None,
            toefl_required=True,
            minimum_toefl=550,
            gre_required=False,
            age_limit=35,
            work_experience="Optional",
            research_experience="Preferred",
            publication="Not Required",
            recommendation_letter=True,
            motivation_letter=True,
            cv_required=True,
            passport_required=True,
        ),
        benefits=Benefits(
            tuition_fee=True,
            monthly_allowance=True,
            accommodation=False,
            health_insurance=True,
            travel_ticket=True,
            research_grant=False,
        ),
    )


class TestScholarshipAggregate:
    """Scholarship aggregate persistence and cascade tests."""

    def test_persist_and_read_aggregate(self, db_session, reference_data, extracted_scholarship):
        country, provider, source = reference_data
        mapper = ScholarshipMapper(db_session)
        repo = ScholarshipRepository(db_session)

        scholarship = mapper.to_orm(extracted_scholarship, source_id=str(source.source_id))
        saved = repo.save(scholarship)
        loaded = repo.get_by_id(saved.scholarship_id)

        assert loaded is not None
        assert loaded.scholarship_name == "MEXT Scholarship 2027 (Test)"
        assert loaded.degree == "Master"
        assert loaded.funding_type == "Fully Funded"
        assert loaded.extraction_status == "pending_review"

        # Cleanup
        db_session.delete(loaded)
        db_session.commit()

    def test_requirement_child(self, db_session, reference_data, extracted_scholarship):
        country, provider, source = reference_data
        mapper = ScholarshipMapper(db_session)
        repo = ScholarshipRepository(db_session)

        scholarship = mapper.to_orm(extracted_scholarship, source_id=str(source.source_id))
        saved = repo.save(scholarship)
        loaded = repo.get_by_id(saved.scholarship_id)

        req = loaded.requirement
        assert req is not None
        assert req.minimum_gpa == 3.5
        assert req.toefl_required is True
        assert req.minimum_toefl == 550
        assert req.age_limit == 35
        assert req.research_experience == "Preferred"

        db_session.delete(loaded)
        db_session.commit()

    def test_benefit_child(self, db_session, reference_data, extracted_scholarship):
        country, provider, source = reference_data
        mapper = ScholarshipMapper(db_session)
        repo = ScholarshipRepository(db_session)

        scholarship = mapper.to_orm(extracted_scholarship, source_id=str(source.source_id))
        saved = repo.save(scholarship)
        loaded = repo.get_by_id(saved.scholarship_id)

        ben = loaded.benefit
        assert ben is not None
        assert ben.tuition_fee is True
        assert ben.monthly_allowance is True
        assert ben.accommodation is False
        assert ben.health_insurance is True

        db_session.delete(loaded)
        db_session.commit()

    def test_timeline_child(self, db_session, reference_data, extracted_scholarship):
        country, provider, source = reference_data
        mapper = ScholarshipMapper(db_session)
        repo = ScholarshipRepository(db_session)

        scholarship = mapper.to_orm(extracted_scholarship, source_id=str(source.source_id))
        saved = repo.save(scholarship)
        loaded = repo.get_by_id(saved.scholarship_id)

        tl = loaded.timeline
        assert tl is not None
        assert tl.application_open == date(2026, 4, 1)
        assert tl.application_deadline == date(2026, 5, 31)
        assert tl.study_start == date(2027, 4, 1)

        db_session.delete(loaded)
        db_session.commit()

    def test_cascade_delete(self, db_session, reference_data, extracted_scholarship):
        country, provider, source = reference_data
        mapper = ScholarshipMapper(db_session)
        repo = ScholarshipRepository(db_session)

        scholarship = mapper.to_orm(extracted_scholarship, source_id=str(source.source_id))
        saved = repo.save(scholarship)
        loaded = repo.get_by_id(saved.scholarship_id)

        req_id = loaded.requirement.requirement_id
        ben_id = loaded.benefit.benefit_id
        tl_id = loaded.timeline.timeline_id
        sch_id = loaded.scholarship_id

        db_session.delete(loaded)
        db_session.commit()

        assert db_session.query(ScholarshipRequirement).filter_by(requirement_id=req_id).first() is None
        assert db_session.query(ScholarshipBenefit).filter_by(benefit_id=ben_id).first() is None
        assert db_session.query(ScholarshipTimeline).filter_by(timeline_id=tl_id).first() is None
        assert db_session.query(Scholarship).filter_by(scholarship_id=sch_id).first() is None

    def test_orm_relationships(self, db_session, reference_data, extracted_scholarship):
        country, provider, source = reference_data
        mapper = ScholarshipMapper(db_session)
        repo = ScholarshipRepository(db_session)

        scholarship = mapper.to_orm(extracted_scholarship, source_id=str(source.source_id))
        saved = repo.save(scholarship)
        loaded = repo.get_by_id(saved.scholarship_id)

        assert loaded.provider is not None
        assert loaded.country is not None
        assert loaded.source is not None
        assert loaded.versions == []

        db_session.delete(loaded)
        db_session.commit()
