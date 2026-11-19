"""Public API contract tests for legitimately incomplete scholarship data.

Regression tests for a real defect found during the M9 validation run: a
scholarship whose official page stated no degree and no funding type was
published, and the public list endpoint returned HTTP 500. The API schemas
declared ``degree: str`` and ``funding_type: str`` while the database columns
are nullable, so ordinary data crashed the endpoint.

A published record with missing optional fields is normal. The API must render
it, with the absent fields as null, rather than fail.
"""

from __future__ import annotations

import uuid

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry

pytestmark = pytest.mark.api


@pytest.fixture
def incomplete_record(exploration_session):
    """An approved record with no degree, no funding type and no fields of study.

    This is what a real extraction produces when the official page does not
    state them, which the review gates permit: those fields are optional to
    publish precisely because pages legitimately omit them.
    """
    session = exploration_session
    country = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]

    provider = Provider(
        provider_code=f"INCOMPLETE_{suffix.upper()}"[:32],
        provider_name="Temasek Polytechnic",
        provider_type=ProviderType.UNIVERSITY,
        country_id=country.country_id,
        official_url="https://www.tp.edu.sg/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Incomplete source {suffix}",
        country_id=country.country_id,
        official_url=f"https://www.tp.edu.sg/{suffix}/",
        crawl_entry_url=f"https://www.tp.edu.sg/{suffix}/en/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()

    record = Scholarship(
        # Deliberately unique: the shared development database already holds a
        # real Singapore scholarship with a very similar name, and a test that
        # matches it passes for the wrong reason.
        scholarship_name=f"Incomplete Fixture Programme {suffix}",
        degree=None,
        funding_type=None,
        field_of_study=[],
        official_page_url=f"https://www.tp.edu.sg/{suffix}/scholarships/pfp.html",
        application_url=None,
        provider_id=provider.provider_id,
        country_id=country.country_id,
        source_id=source.source_id,
        extraction_status="approved",
        deadline_state="active",
        provenance_origin="exploration",
        identity_key=uuid.uuid4().hex,
    )
    session.add(record)
    session.flush()
    return record


@pytest.fixture
def public_client(client, exploration_session, monkeypatch):
    """Test client whose public scholarship routes read the isolated session.

    These routers manage their own session, which is correct in production and
    wrong in tests: an uncommitted fixture row is invisible to them, so the
    endpoint would return data from the shared database instead of the record
    under test.
    """
    from api.routers import scholarships as scholarships_module

    monkeypatch.setattr(scholarships_module, "SessionLocal", lambda: exploration_session)
    return client


@pytest.fixture
def fixture_query(incomplete_record):
    return incomplete_record.scholarship_name


class TestPublicListWithIncompleteData:
    def test_list_does_not_500_on_missing_optional_fields(self, public_client, fixture_query):
        response = public_client.get(
            "/api/v1/scholarships", params={"q": fixture_query, "limit": 50}
        )
        assert response.status_code == 200, response.text
        names = [r["scholarship_name"] for r in response.json()["results"]]
        assert fixture_query in names

    def test_absent_fields_are_returned_as_null_not_invented(
        self, public_client, fixture_query
    ):
        response = public_client.get(
            "/api/v1/scholarships", params={"q": fixture_query, "limit": 50}
        )
        row = next(r for r in response.json()["results"] if r["scholarship_name"] == fixture_query)
        assert row["degree"] is None
        assert row["funding_type"] is None
        assert row["field_of_study"] == []

    def test_detail_does_not_500_on_missing_optional_fields(self, public_client, incomplete_record):
        response = public_client.get(f"/api/v1/scholarships/{incomplete_record.scholarship_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["degree"] is None
        assert body["funding_type"] is None
        assert body["application_url"] is None


class TestMatchingWithIncompleteData:
    def test_matching_does_not_500_on_missing_optional_fields(self, public_client, incomplete_record):
        """Scoring reads degree and funding, so a null must degrade the score
        rather than raise."""
        response = public_client.post(
            "/api/v1/matching",
            json={
                "target_country": "Japan",
                "degree": "Master",
                "field_of_study": ["Computer Science"],
                "current_gpa": 3.5,
                "ielts_score": 7.0,
                "research_experience": "Preferred",
                "work_experience": "Optional",
                "publication": "Not Required",
                "leadership": True,
                "funding_preference": "Fully Funded",
            },
        )
        assert response.status_code == 200, response.text
        scores = [r["match_score"] for r in response.json()["results"]]
        assert all(0 <= s <= 100 for s in scores)
