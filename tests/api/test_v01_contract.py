"""V0.1 production-cut contract tests.

Three things are asserted here, and they are the ones a production cut cannot
get wrong:

  * **No sentinel leaks.** A public response must never contain the string
    "Unknown" standing in for a provider or a country. Null is the honest
    answer; a placeholder word is a fabricated value with a JSON type on it.
  * **`total` means something.** A client that receives a Top-N page must be
    able to tell it is truncated.
  * **The publication boundary holds.** PENDING_REVIEW, REJECTED and
    NEEDS_CORRECTION records are invisible on every public endpoint, and an
    unpublished id is a 404 rather than a 403 that confirms it exists.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from api.app import app
from database.models.scholarship import Scholarship

SENTINEL_VALUES = {"unknown", "n/a", "none", "not specified", "null"}

PROFILE = {
    "target_country": "United Kingdom",
    "degree": "Master",
    "field_of_study": ["Computer Science"],
    "current_gpa": 3.5,
    "ielts_score": 7.0,
    "toefl_score": None,
    "research_experience": "Not Required",
    "work_experience": "Optional",
    "publication": "Not Required",
    "leadership": False,
    "funding_preference": "Fully Funded",
}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _published_ids(session) -> list[str]:
    return [
        str(s.scholarship_id)
        for s in session.query(Scholarship).filter(
            Scholarship.extraction_status == "approved"
        )
    ]


def _unpublished_ids(session) -> dict[str, str]:
    return {
        str(s.scholarship_id): s.extraction_status
        for s in session.query(Scholarship).filter(
            Scholarship.extraction_status != "approved"
        )
    }


class TestNoSentinelInPublicResponses:
    def test_list_never_invents_a_provider_or_country(self, client):
        response = client.get("/api/v1/scholarships", params={"limit": 100})
        assert response.status_code == 200
        for row in response.json()["results"]:
            for field in ("provider_name", "country"):
                value = row.get(field)
                assert value is None or (isinstance(value, str) and value.strip())
                assert (value or "").casefold() not in SENTINEL_VALUES, (
                    f"{row['scholarship_id']}.{field} is the placeholder {value!r}"
                )

    def test_detail_never_invents_a_provider_or_country(self, client, session):
        for scholarship_id in _published_ids(session):
            response = client.get(f"/api/v1/scholarships/{scholarship_id}")
            assert response.status_code == 200
            body = response.json()
            for field in ("provider_name", "provider_type", "country"):
                value = body.get(field)
                assert value is None or (isinstance(value, str) and value.strip())
                assert (value or "").casefold() not in SENTINEL_VALUES

    def test_recommendations_never_invent_a_provider_or_country(self, client):
        response = client.post("/api/v1/matching", json=PROFILE)
        assert response.status_code == 200
        for row in response.json()["results"]:
            for field in ("provider_name", "country"):
                value = row.get(field)
                assert value is None or isinstance(value, str)
                assert (value or "").casefold() not in SENTINEL_VALUES

    def test_the_unresolved_branch_returns_null_not_a_placeholder(self):
        """The regression itself, tested at the mapper.

        `scholarship.provider_id` and `country_id` are NOT NULL in the database,
        so the "Unknown" branch was unreachable with any valid row — it was
        dead code, not a live leak. The branch is still tested directly, because
        dead code that fabricates a value is one schema migration away from
        being live code that does.
        """
        from api.routers.scholarships import _to_detail, _to_summary

        class _Row:
            scholarship_id = uuid.uuid4()
            scholarship_name = "Example Award"
            provider = None
            country = None
            university = None
            degree = "Master"
            degree_levels = []
            funding_type = "Fully Funded"
            field_of_study = ["Computer Science"]
            official_page_url = "https://example.edu/award"
            application_url = None
            last_verified_at = None
            requirement = None
            benefit = None
            timeline = None

        summary = _to_summary(_Row())
        assert summary.provider_name is None
        assert summary.country is None

        detail = _to_detail(_Row())
        assert detail.provider_name is None
        assert detail.country is None
        assert detail.provider_type is None

    def test_the_columns_making_them_unreachable_are_not_nullable(self):
        """If these ever become nullable, the branch above becomes reachable —
        which is fine, because it now returns None. This test records why the
        fix was not a live bug."""
        table = Scholarship.__table__
        assert table.c.provider_id.nullable is False
        assert table.c.country_id.nullable is False


class TestRecommendationTotalIsSemanticallyCorrect:
    def test_total_is_the_match_set_and_returned_is_the_page(self, client):
        response = client.post("/api/v1/matching", json=PROFILE)
        assert response.status_code == 200
        body = response.json()
        assert body["returned"] == len(body["results"])
        assert body["total"] >= body["returned"], (
            "total is the size of the whole match set and cannot be smaller "
            "than the page returned"
        )

    def test_total_is_not_merely_the_page_length(self, client, session):
        """When more scholarships match than the Top-N page holds, the two
        numbers must differ. Otherwise the contract is indistinguishable from
        the old `total = len(results)`."""
        approved = len(_published_ids(session))
        if approved <= 10:
            pytest.skip("catalogue smaller than the Top-N cut; cannot observe truncation")

        response = client.post("/api/v1/matching", json=PROFILE)
        body = response.json()
        assert body["returned"] == len(body["results"])
        if len(body["results"]) == 10:
            assert body["total"] > 10, (
                "the page is capped at 10, so total must report the larger set"
            )

    def test_both_canonical_and_frontend_paths_report_the_same_contract(self, client):
        canonical = client.post("/api/v1/recommendations", json=PROFILE).json()
        frontend = client.post("/api/v1/matching", json=PROFILE).json()
        assert canonical == frontend


class TestPublicationBoundaryHolds:
    def test_list_contains_only_approved_records(self, client, session):
        approved = set(_published_ids(session))
        response = client.get("/api/v1/scholarships", params={"limit": 100})
        listed = {row["scholarship_id"] for row in response.json()["results"]}
        assert listed <= approved, f"unpublished records listed: {listed - approved}"

    def test_search_cannot_surface_an_unpublished_record(self, client, session):
        """Search runs against the approved set; this asserts it stays that way."""
        unpublished = _unpublished_ids(session)
        if not unpublished:
            pytest.skip("no unpublished records to test against")
        needle = "scholarship"
        response = client.get("/api/v1/scholarships", params={"q": needle, "limit": 100})
        assert response.status_code == 200
        for row in response.json()["results"]:
            assert row["scholarship_id"] not in unpublished

    @pytest.mark.parametrize("state", ["pending_review", "rejected", "needs_correction"])
    def test_detail_of_an_unpublished_record_is_404(self, client, session, state):
        record = (
            session.query(Scholarship)
            .filter(Scholarship.extraction_status == state)
            .first()
        )
        if record is None:
            pytest.skip(f"no record in state {state}")
        response = client.get(f"/api/v1/scholarships/{record.scholarship_id}")
        assert response.status_code == 404

    def test_matching_never_returns_an_unpublished_record(self, client, session):
        unpublished = set(_unpublished_ids(session))
        if not unpublished:
            pytest.skip("no unpublished records to test against")
        response = client.post("/api/v1/matching", json=PROFILE)
        returned = {row["scholarship_id"] for row in response.json()["results"]}
        assert not (returned & unpublished)

    def test_an_unknown_id_is_404_not_500(self, client):
        response = client.get(f"/api/v1/scholarships/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_a_malformed_id_is_404_not_500(self, client):
        response = client.get("/api/v1/scholarships/not-a-uuid")
        assert response.status_code == 404


class TestErrorBehaviour:
    def test_an_invalid_profile_is_422_with_field_messages(self, client):
        response = client.post("/api/v1/matching", json={"target_country": "Japan"})
        assert response.status_code == 422
        assert response.json()["detail"], "a 422 must say what is wrong"

    def test_an_empty_search_returns_an_empty_page_not_an_error(self, client):
        response = client.get(
            "/api/v1/scholarships",
            params={"q": "zzzzzz-no-such-scholarship-zzzzzz", "limit": 10},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["results"] == []
        assert body["total"] == 0

    def test_pagination_is_bounded(self, client):
        assert client.get("/api/v1/scholarships", params={"limit": 0}).status_code == 422
        assert client.get("/api/v1/scholarships", params={"limit": 5000}).status_code == 422
        assert client.get("/api/v1/scholarships", params={"offset": -1}).status_code == 422
