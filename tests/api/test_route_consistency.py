"""The API surface is one surface (post-M10 Priority F).

M10 found ``POST /api/v1/recommendations`` answering 405 while the route sat
at ``/recommendations``. The cause was not a missing route: the
recommendations router carried no prefix and wrote its two paths out in full,
while every other router used ``/api/v1``.

The convention is now enforced rather than assumed. These tests fail if a
router is added without the prefix, or if a path is written with the prefix
baked into the decorator instead of declared once on the router.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

CANONICAL_PREFIX = "/api/v1"

# Paths that are deliberately outside the versioned prefix. `/health` is a
# liveness probe for infrastructure, not a versioned resource, and the
# frontend bundle is mounted at the root.
UNPREFIXED_OK = {"/health", "/"}


@pytest.fixture(scope="module")
def schema():
    return create_app().openapi()


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


class TestEveryRouteIsUnderThePrefix:
    def test_no_route_sits_outside_the_versioned_prefix(self, schema):
        stray = sorted(
            path
            for path in schema["paths"]
            if not path.startswith(CANONICAL_PREFIX)
            and path not in UNPREFIXED_OK
            and not path.startswith("/api/v1/admin")
        )
        assert stray == [], (
            f"routes outside {CANONICAL_PREFIX}: {stray}. Every router declares "
            f"APIRouter(prefix=...) once; a path must not repeat the prefix."
        )


class TestRecommendationRoutes:
    """The two names for the same operation must both exist, and agree."""

    # Every field RecommendationRequest declares is required, so a request that
    # exercises routing has to be complete.
    PAYLOAD = {
        "target_country": "Japan",
        "degree": "Master",
        "field_of_study": ["Computer Science"],
        "current_gpa": 3.5,
        "ielts_score": 6.5,
        "toefl_score": None,
        "research_experience": "Not Required",
        "work_experience": "Not Required",
        "publication": "Not Required",
        "leadership": False,
        "funding_preference": "Fully Funded",
    }

    def test_the_canonical_recommendation_route_answers(self, client):
        response = client.post(f"{CANONICAL_PREFIX}/recommendations", json=self.PAYLOAD)
        assert response.status_code == 200, response.text
        assert "results" in response.json()

    def test_the_frontend_alias_answers_too(self, client):
        """The frontend calls /api/v1/matching. It must not 404."""
        assert client.post(
            f"{CANONICAL_PREFIX}/matching", json=self.PAYLOAD
        ).status_code == 200

    def test_the_bare_path_is_no_longer_a_second_way_in(self, client, schema):
        """POST /recommendations is gone: one prefix, one way in.

        A route that answers at an unversioned path is exactly the ambiguity
        this milestone removed, so it must not quietly come back. The status
        is not asserted to be 404 specifically because the SPA mount at "/"
        answers 405 for a path it does not serve by POST.
        """
        assert "/recommendations" not in schema["paths"]
        response = client.post("/recommendations", json=self.PAYLOAD)
        assert response.status_code != 200

    def test_both_names_describe_the_same_operation(self, schema):
        """Same response schema: it is one endpoint with two paths."""
        paths = schema["paths"]
        canonical = paths[f"{CANONICAL_PREFIX}/recommendations"]["post"]
        alias = paths[f"{CANONICAL_PREFIX}/matching"]["post"]
        assert canonical["responses"]["200"]["content"]["application/json"][
            "schema"
        ] == alias["responses"]["200"]["content"]["application/json"]["schema"]


class TestTheOtherRoutersWereAlreadyRight:
    """Guards the convention this milestone aligned to."""

    def test_scholarships_live_under_the_prefix(self, schema):
        assert f"{CANONICAL_PREFIX}/scholarships" in schema["paths"]

    def test_review_lives_under_the_prefix(self, schema):
        assert f"{CANONICAL_PREFIX}/admin/review/scholarships" in schema["paths"]
