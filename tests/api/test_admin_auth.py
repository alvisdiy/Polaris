"""The admin review surface must be closed by default and opened only by token."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app
from api.auth import ADMIN_TOKEN_ENV

CANDIDATES = "/api/v1/admin/review/candidates"
TOKEN = "a-test-operator-token"


def _bare_client() -> TestClient:
    """A client with no default Authorization header."""
    return TestClient(app)


class TestConfiguration:
    def test_unset_token_disables_the_surface(self, monkeypatch):
        """A missing secret fails closed, not open."""
        monkeypatch.delenv(ADMIN_TOKEN_ENV, raising=False)

        response = _bare_client().get(CANDIDATES)

        assert response.status_code == 503
        assert "POLARIS_ADMIN_TOKEN" in response.json()["detail"]

    def test_blank_token_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv(ADMIN_TOKEN_ENV, "   ")

        assert _bare_client().get(CANDIDATES).status_code == 503


class TestAuthentication:
    def test_missing_header_is_rejected(self, monkeypatch):
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)

        response = _bare_client().get(CANDIDATES)

        assert response.status_code == 401
        assert response.headers.get("www-authenticate") == "Bearer"

    def test_wrong_token_is_rejected(self, monkeypatch):
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)

        response = _bare_client().get(
            CANDIDATES, headers={"Authorization": "Bearer not-the-token"}
        )

        assert response.status_code == 401

    def test_wrong_scheme_is_rejected(self, monkeypatch):
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)

        response = _bare_client().get(
            CANDIDATES, headers={"Authorization": f"Basic {TOKEN}"}
        )

        assert response.status_code == 401

    def test_empty_bearer_value_is_rejected(self, monkeypatch):
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)

        response = _bare_client().get(
            CANDIDATES, headers={"Authorization": "Bearer "}
        )

        assert response.status_code == 401

    def test_correct_token_is_accepted(self, monkeypatch):
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)

        response = _bare_client().get(
            CANDIDATES, headers={"Authorization": f"Bearer {TOKEN}"}
        )

        assert response.status_code == 200, response.text
        assert "results" in response.json()


class TestEveryAdminRouteIsGuarded:
    def test_a_mutating_route_also_rejects_anonymous_callers(self, monkeypatch):
        """The guard is on the router, so it cannot be forgotten per-route."""
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)

        response = _bare_client().post(
            "/api/v1/admin/review/scholarships/00000000-0000-0000-0000-000000000000/approve",
            json={"actor": "anonymous", "reason": "should never run"},
        )

        assert response.status_code == 401
