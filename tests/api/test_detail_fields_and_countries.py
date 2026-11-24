"""Public detail fields and the countries endpoint.

Requirement columns (GRE, age limit, recommendation/motivation letter,
CV, passport) and the university were stored for every record but never
exposed by the public API, so the detail page could not show them. The
country filter lists were hardcoded in two frontend components and
disagreed; they now come from GET /scholarships/countries, which must
list only countries that have a published record.
"""

from __future__ import annotations

import uuid

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.source_registry import SourceRegistry
from database.models.university import University
from services.review import ReviewStatus


@pytest.fixture
def world(exploration_session):
    session = exploration_session
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    kr = session.query(Country).filter(Country.iso2 == "KR").first()
    suffix = uuid.uuid4().hex[:8]

    provider = Provider(
        provider_code=f"FIELDS_{suffix.upper()}"[:32],
        provider_name="Fields Test Ministry",
        provider_type=ProviderType.GOVERNMENT,
        country_id=jp.country_id,
        official_url="https://www.studyinjapan.go.jp/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Fields source {suffix}",
        country_id=jp.country_id,
        official_url=f"https://www.studyinjapan.go.jp/{suffix}/",
        crawl_entry_url=f"https://www.studyinjapan.go.jp/{suffix}/en/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    university = University(
        university_code=f"FTU{suffix.upper()}"[:32],
        name=f"Fields Test University {suffix}",
        country_id=jp.country_id,
    )
    session.add_all([provider, source, university])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()

    def make(country, state, name):
        record = Scholarship(
            scholarship_name=name,
            degree="Master",
            funding_type="Fully Funded",
            field_of_study=["Engineering"],
            official_page_url="https://www.studyinjapan.go.jp/en/",
            provider_id=provider.provider_id,
            country_id=country.country_id,
            source_id=source.source_id,
            university_id=university.university_id if country is jp else None,
            extraction_status=state,
            deadline_state="active",
            provenance_origin="exploration",
            identity_key=uuid.uuid4().hex,
        )
        session.add(record)
        session.flush()
        return record

    approved = make(jp, ReviewStatus.APPROVED, f"Fields Approved {suffix}")
    session.add(
        ScholarshipRequirement(
            scholarship_id=approved.scholarship_id,
            minimum_gpa=3.0,
            ielts_required=True,
            minimum_ielts=6.5,
            gre_required=True,
            age_limit=30,
            recommendation_letter=True,
            motivation_letter=False,
            cv_required=True,
            passport_required=False,
        )
    )
    make(kr, ReviewStatus.PENDING_REVIEW, f"Fields Pending KR {suffix}")
    session.flush()
    return {"approved": approved, "session": session}


@pytest.fixture
def public_client(client, world, monkeypatch):
    from api.routers import scholarships as scholarships_module

    monkeypatch.setattr(scholarships_module, "SessionLocal", lambda: world["session"])
    return client


class TestDetailFields:
    def test_requirement_fields_are_exposed(self, public_client, world):
        response = public_client.get(
            f"/api/v1/scholarships/{world['approved'].scholarship_id}"
        )
        assert response.status_code == 200
        requirement = response.json()["requirement"]
        assert requirement["gre_required"] is True
        assert requirement["age_limit"] == 30
        assert requirement["recommendation_letter"] is True
        assert requirement["motivation_letter"] is False
        assert requirement["cv_required"] is True
        assert requirement["passport_required"] is False

    def test_university_is_exposed(self, public_client, world):
        response = public_client.get(
            f"/api/v1/scholarships/{world['approved'].scholarship_id}"
        )
        assert response.status_code == 200
        assert response.json()["university"].startswith("Fields Test University")


class TestCountriesEndpoint:
    def test_lists_only_countries_with_published_records(self, public_client, world):
        response = public_client.get("/api/v1/scholarships/countries")
        assert response.status_code == 200
        names = response.json()
        assert "Japan" in names
        # Korea's only record here is pending review: not a usable filter.
        assert "South Korea" not in names and "Korea" not in names
