"""Unit tests for ScholarshipMapper."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.university import University
from services.ingestion.extractor import Benefits, Eligibility, ExtractedScholarship, Timeline
from services.scholarship.mapper import ScholarshipMapper, _parse_date

pytestmark = pytest.mark.unit


# --- _parse_date ---


def test_parse_date_none():
    assert _parse_date(None) is None


def test_parse_date_valid():
    assert _parse_date("2025-03-15") == date(2025, 3, 15)


def test_parse_date_invalid():
    with pytest.raises(ValueError):
        _parse_date("not-a-date")


# --- Fixtures ---


def _mock_provider(name: str = "MEXT") -> MagicMock:
    p = MagicMock(spec=Provider)
    p.provider_id = uuid.uuid4()
    p.provider_name = name
    return p


def _mock_country(name: str = "Japan") -> MagicMock:
    c = MagicMock(spec=Country)
    c.country_id = uuid.uuid4()
    c.name = name
    return c


def _mock_university(name: str = "University of Tokyo") -> MagicMock:
    u = MagicMock(spec=University)
    u.university_id = uuid.uuid4()
    u.name = name
    return u


def _make_extracted(**overrides) -> ExtractedScholarship:
    today = date.today()
    defaults = dict(
        scholarship_name="MEXT Scholarship",
        provider_name="MEXT",
        scholarship_type="Government",
        country="Japan",
        university=None,
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Computer Science"],
        application_url="https://example.com/apply",
        official_source="https://example.com",
        timeline=Timeline(
            application_open=(today - timedelta(days=30)).isoformat(),
            application_deadline=(today + timedelta(days=300)).isoformat(),
        ),
        eligibility=Eligibility(
            minimum_gpa=3.0,
            ielts_required=True,
            minimum_ielts=6.5,
            work_experience="Optional",
        ),
        benefits=Benefits(
            tuition_fee=True,
            monthly_allowance=True,
            health_insurance=True,
        ),
    )
    defaults.update(overrides)
    return ExtractedScholarship(**defaults)


# --- to_orm ---


def test_to_orm_creates_scholarship_with_children():
    session = MagicMock()
    provider = _mock_provider()
    country = _mock_country()

    session.query.return_value.filter.return_value.first.side_effect = [
        provider,
        country,
    ]

    mapper = ScholarshipMapper(session)
    extracted = _make_extracted()
    result = mapper.to_orm(extracted, source_id="src-123")

    assert result.scholarship_name == "MEXT Scholarship"
    assert result.degree == "Master"
    assert result.funding_type == "Fully Funded"
    assert result.field_of_study == ["Computer Science"]
    assert result.extraction_status == "pending_review"
    assert result.provider_id == provider.provider_id
    assert result.country_id == country.country_id
    assert result.university_id is None

    # Children
    assert result.requirement is not None
    assert result.requirement.minimum_gpa == 3.0
    assert result.requirement.ielts_required is True
    assert result.requirement.minimum_ielts == 6.5

    assert result.benefit is not None
    assert result.benefit.tuition_fee is True
    assert result.benefit.monthly_allowance is True

    today = date.today()
    assert result.timeline is not None
    assert result.timeline.application_open == today - timedelta(days=30)
    assert result.timeline.application_deadline == today + timedelta(days=300)


def test_to_orm_with_university():
    session = MagicMock()
    provider = _mock_provider()
    country = _mock_country()
    university = _mock_university()

    session.query.return_value.filter.return_value.first.side_effect = [
        provider,
        country,
        university,
    ]

    mapper = ScholarshipMapper(session)
    extracted = _make_extracted(university="University of Tokyo")
    result = mapper.to_orm(extracted, source_id="src-123")

    assert result.university_id == university.university_id


def test_to_orm_university_not_found_returns_none():
    session = MagicMock()
    provider = _mock_provider()
    country = _mock_country()

    session.query.return_value.filter.return_value.first.side_effect = [
        provider,
        country,
        None,
    ]

    mapper = ScholarshipMapper(session)
    extracted = _make_extracted(university="Unknown University")
    result = mapper.to_orm(extracted, source_id="src-123")

    assert result.university_id is None


def test_to_orm_missing_provider_raises():
    session = MagicMock()
    country = _mock_country()

    session.query.return_value.filter.return_value.first.side_effect = [
        None,
        country,
    ]

    mapper = ScholarshipMapper(session)
    extracted = _make_extracted()

    with pytest.raises(ValueError, match="Provider not found"):
        mapper.to_orm(extracted, source_id="src-123")


def test_to_orm_missing_country_raises():
    session = MagicMock()
    provider = _mock_provider()

    session.query.return_value.filter.return_value.first.side_effect = [
        provider,
        None,
    ]

    mapper = ScholarshipMapper(session)
    extracted = _make_extracted()

    with pytest.raises(ValueError, match="Country not found"):
        mapper.to_orm(extracted, source_id="src-123")


def test_to_orm_timeline_with_none_dates():
    session = MagicMock()
    provider = _mock_provider()
    country = _mock_country()

    session.query.return_value.filter.return_value.first.side_effect = [
        provider,
        country,
    ]

    today = date.today()
    expected_deadline = today + timedelta(days=300)
    mapper = ScholarshipMapper(session)
    extracted = _make_extracted(
        timeline=Timeline(
            application_open=None,
            application_deadline=expected_deadline.isoformat(),
            interview_date=None,
            result_date=None,
            study_start=None,
        )
    )
    result = mapper.to_orm(extracted, source_id="src-123")

    assert result.timeline.application_open is None
    assert result.timeline.application_deadline == expected_deadline
    assert result.timeline.interview_date is None
    assert result.timeline.result_date is None
    assert result.timeline.study_start is None


def test_to_orm_eligibility_with_none_values():
    session = MagicMock()
    provider = _mock_provider()
    country = _mock_country()

    session.query.return_value.filter.return_value.first.side_effect = [
        provider,
        country,
    ]

    mapper = ScholarshipMapper(session)
    extracted = _make_extracted(
        eligibility=Eligibility(
            minimum_gpa=None,
            ielts_required=None,
            minimum_ielts=None,
            toefl_required=None,
            work_experience=None,
            research_experience=None,
            publication=None,
        )
    )
    result = mapper.to_orm(extracted, source_id="src-123")

    assert result.requirement.minimum_gpa is None
    assert result.requirement.ielts_required is False
    assert result.requirement.work_experience is None
