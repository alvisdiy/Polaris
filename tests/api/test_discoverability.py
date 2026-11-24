"""Discoverability + caching surface: funding filter, sitemap, robots,
cache headers.

The funding filter is an equality match on a controlled vocabulary.
The sitemap advertises exactly the records the detail endpoint would
serve (published, including expired-as-archive) and nothing else.
Public catalogue GETs carry a short shared-cache lifetime; the
catalogue changes nightly, not per request.
"""

from __future__ import annotations

import uuid

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from services.review import ReviewStatus


@pytest.fixture
def world(exploration_session):
    session = exploration_session
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]

    provider = Provider(
        provider_code=f"DISC_{suffix.upper()}"[:32],
        provider_name="Discoverability Ministry",
        provider_type=ProviderType.GOVERNMENT,
        country_id=jp.country_id,
        official_url="https://www.studyinjapan.go.jp/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Discoverability source {suffix}",
        country_id=jp.country_id,
        official_url=f"https://www.studyinjapan.go.jp/{suffix}/",
        crawl_entry_url=f"https://www.studyinjapan.go.jp/{suffix}/en/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()

    def make(state, funding, name):
        record = Scholarship(
            scholarship_name=name,
            degree="Master",
            funding_type=funding,
            field_of_study=["Engineering"],
            official_page_url="https://www.studyinjapan.go.jp/en/",
            provider_id=provider.provider_id,
            country_id=jp.country_id,
            source_id=source.source_id,
            extraction_status=state,
            deadline_state="active",
            provenance_origin="exploration",
            identity_key=uuid.uuid4().hex,
        )
        session.add(record)
        session.flush()
        return record

    full = make(ReviewStatus.APPROVED, "Fully Funded", f"Disc Full {suffix}")
    partial = make(ReviewStatus.APPROVED, "Partial Funded", f"Disc Partial {suffix}")
    pending = make(ReviewStatus.PENDING_REVIEW, "Fully Funded", f"Disc Pending {suffix}")
    return {"full": full, "partial": partial, "pending": pending, "session": session}


@pytest.fixture
def public_client(client, world, monkeypatch):
    from api.routers import scholarships as scholarships_module

    monkeypatch.setattr(scholarships_module, "SessionLocal", lambda: world["session"])
    monkeypatch.setattr("database.session.SessionLocal", lambda: world["session"])
    return client


class TestFundingFilter:
    def test_funding_filter_is_an_exact_vocabulary_match(self, public_client, world):
        response = public_client.get(
            "/api/v1/scholarships", params={"funding": "Fully Funded"}
        )
        assert response.status_code == 200
        names = [r["scholarship_name"] for r in response.json()["results"]]
        assert world["full"].scholarship_name in names
        # "Fully Funded" must not substring-match "Partial Funded", and a
        # pending record never appears regardless of funding.
        assert world["partial"].scholarship_name not in names
        assert world["pending"].scholarship_name not in names

    def test_list_response_is_publicly_cacheable(self, public_client, world):
        response = public_client.get("/api/v1/scholarships")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "public, max-age=300"


class TestCrawlerSurfaces:
    def test_sitemap_lists_published_detail_pages_only(self, public_client, world):
        response = public_client.get("/sitemap.xml")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/xml")
        body = response.text
        assert f"/scholarships/{world['full'].scholarship_id}" in body
        assert f"/scholarships/{world['partial'].scholarship_id}" in body
        assert f"/scholarships/{world['pending'].scholarship_id}" not in body
        assert "/discover" in body

    def test_robots_points_at_the_sitemap(self, public_client, world):
        response = public_client.get("/robots.txt")
        assert response.status_code == 200
        assert "Sitemap: " in response.text
        assert "/sitemap.xml" in response.text
        assert "Disallow: /api/" in response.text
