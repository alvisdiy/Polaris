"""Search quality + rate limiting.

Search used to match only the scholarship name as a substring, so a
provider query, a field-of-study query, or a one-letter typo all
returned an empty catalogue. These tests pin the wider contract:
name, provider and field substrings, plus trigram typo tolerance.

The rate-limit tests pin the policy mapping (admin exempt, matching
strictest) and the 429 behaviour end to end, with the policy shrunk
via monkeypatching so the suite never depends on real volumes.
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
def searchable(exploration_session):
    session = exploration_session
    jp = session.query(Country).filter(Country.iso2 == "JP").first()
    suffix = uuid.uuid4().hex[:8]

    provider = Provider(
        provider_code=f"ZE_{suffix.upper()}"[:32],
        provider_name="Zephyr Education Trust",
        provider_type=ProviderType.FOUNDATION,
        country_id=jp.country_id,
        official_url="https://example.org/",
        verification_status="verified",
    )
    source = SourceRegistry(
        source_name=f"Search source {suffix}",
        country_id=jp.country_id,
        official_url=f"https://example.org/{suffix}/",
        crawl_entry_url=f"https://example.org/{suffix}/en/",
        crawl_method="Playwright",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
    )
    session.add_all([provider, source])
    session.flush()
    source.provider_id = provider.provider_id
    session.flush()

    record = Scholarship(
        scholarship_name="Brightpath Scholars Award",
        degree="Master",
        funding_type="Fully Funded",
        field_of_study=["Astrophysics"],
        official_page_url="https://example.org/brightpath",
        provider_id=provider.provider_id,
        country_id=jp.country_id,
        source_id=source.source_id,
        extraction_status=ReviewStatus.APPROVED,
        deadline_state="active",
        provenance_origin="exploration",
        identity_key=uuid.uuid4().hex,
    )
    session.add(record)
    session.flush()
    return record


@pytest.fixture
def search_client(client, searchable, exploration_session, monkeypatch):
    from api.routers import scholarships as scholarships_module

    monkeypatch.setattr(scholarships_module, "SessionLocal", lambda: exploration_session)
    return client


def _names(response):
    return [r["scholarship_name"] for r in response.json()["results"]]


class TestSearchQuality:
    def test_search_matches_provider_name(self, search_client, searchable):
        response = search_client.get("/api/v1/scholarships", params={"q": "zephyr"})
        assert searchable.scholarship_name in _names(response)

    def test_search_matches_field_of_study(self, search_client, searchable):
        response = search_client.get("/api/v1/scholarships", params={"q": "astrophysics"})
        assert searchable.scholarship_name in _names(response)

    def test_search_still_matches_name_substring(self, search_client, searchable):
        response = search_client.get("/api/v1/scholarships", params={"q": "brightpath"})
        assert searchable.scholarship_name in _names(response)

    def test_search_tolerates_a_typo(self, search_client, searchable):
        # "brightpatt" is not a substring of "Brightpath" — only the
        # trigram fallback can find this record.
        response = search_client.get("/api/v1/scholarships", params={"q": "brightpatt"})
        assert searchable.scholarship_name in _names(response)

    def test_search_unrelated_term_stays_empty(self, search_client, searchable):
        response = search_client.get(
            "/api/v1/scholarships", params={"q": "underwater basket weaving"}
        )
        assert searchable.scholarship_name not in _names(response)


class TestRateLimitPolicy:
    def test_admin_surface_is_exempt(self):
        from api.rate_limit import bucket_for

        assert bucket_for("POST", "/api/v1/admin/review/scholarships/x/approve") is None
        assert bucket_for("GET", "/api/v1/admin/review/scholarships") is None

    def test_matching_gets_the_strictest_budget(self):
        from api.rate_limit import bucket_for

        matching = bucket_for("POST", "/api/v1/recommendations")
        reads = bucket_for("GET", "/api/v1/scholarships")
        assert matching is not None and reads is not None
        assert matching[1] < reads[1]

    def test_limiter_blocks_after_the_budget(self):
        from api.rate_limit import SlidingWindowLimiter

        limiter = SlidingWindowLimiter()
        assert limiter.allow("client:a", 3)
        assert limiter.allow("client:a", 3)
        assert limiter.allow("client:a", 3)
        assert not limiter.allow("client:a", 3)
        # A different client has its own budget.
        assert limiter.allow("client:b", 3)


class TestRateLimitHttp:
    def test_exceeding_the_budget_returns_429(self, client, monkeypatch):
        import api.rate_limit as rate_limit_module
        from api.app import app

        monkeypatch.setattr(
            rate_limit_module, "POLICY", [("GET", "/api/v1/", 3)]
        )
        app.state.rate_limiter.reset()
        try:
            statuses = [
                client.get("/api/v1/scholarships").status_code for _ in range(5)
            ]
        finally:
            app.state.rate_limiter.reset()
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429
        assert statuses[4] == 429
