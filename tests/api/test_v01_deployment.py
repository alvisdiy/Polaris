"""V0.1 deployment-readiness tests.

These assert the things a production cut breaks on and a unit test never sees:
deep links, unknown API paths, path traversal through the static handler, and
the cross-origin policy. The first three were found by
``scripts/v01_smoke.py`` against a live server, not by reasoning.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

# The SPA fallback only exists when a production build is present. In CI the
# frontend is not always built, so the routing contract is asserted only when
# the build directory exists — and that condition is stated rather than hidden.
BUILD_PRESENT = pytest.mark.skipif(
    not (__import__("pathlib").Path(__file__).resolve().parents[2]
         / "frontend" / "dist" / "index.html").exists(),
    reason="frontend/dist not built; the SPA fallback is not registered",
)


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


class TestHealthCheck:
    def test_health_reports_the_database(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"


@BUILD_PRESENT
class TestSinglePageRouting:
    """A history-routed SPA must resolve every route it declares.

    ``StaticFiles(html=True)`` serves the directory and 404s everything else,
    which breaks a bookmark, a shared link, or a refresh on any route but
    ``/``. The shortlist lives in localStorage and only survives a reload if
    the reload resolves.
    """

    @pytest.mark.parametrize(
        "route",
        ["/", "/discover", "/match", "/compare", "/saved", "/about"],
    )
    def test_client_routes_resolve(self, client, route):
        assert client.get(route).status_code == 200

    def test_a_deep_link_to_a_detail_page_resolves(self, client):
        assert client.get("/scholarships/00000000-0000-0000-0000-000000000000").status_code == 200

    def test_an_unknown_api_path_is_404_json_not_the_spa_shell(self, client):
        response = client.get("/api/v1/definitely-not-a-route")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert "detail" in response.json()

    def test_the_api_is_not_shadowed_by_the_spa_fallback(self, client):
        assert client.get("/api/v1/scholarships?limit=1").status_code == 200

    def test_path_traversal_does_not_escape_the_build_directory(self, client):
        """A crafted path must not serve a file from outside frontend/dist."""
        response = client.get("/../../.env")
        assert response.status_code == 200
        body = response.text
        assert "DATABASE_PASSWORD" not in body
        assert "DATABASE_URL" not in body


class TestCorsPolicy:
    def test_cors_is_off_by_default(self):
        """Single-origin deployment: no CORS headers unless origins are named.

        This API has no authentication, so an accidental wildcard would let any
        site on the internet read the whole catalogue.
        """
        response = TestClient(create_app()).get(
            "/api/v1/scholarships?limit=1",
            headers={"Origin": "https://evil.example"},
        )
        assert "access-control-allow-origin" not in response.headers

    def test_configured_origins_are_honoured(self, monkeypatch):
        monkeypatch.setenv("POLARIS_ALLOWED_ORIGINS", "https://polaris.example")
        response = TestClient(create_app()).get(
            "/api/v1/scholarships?limit=1",
            headers={"Origin": "https://polaris.example"},
        )
        assert response.headers.get("access-control-allow-origin") == "https://polaris.example"

    def test_an_unlisted_origin_is_not_allowed(self, monkeypatch):
        monkeypatch.setenv("POLARIS_ALLOWED_ORIGINS", "https://polaris.example")
        response = TestClient(create_app()).get(
            "/api/v1/scholarships?limit=1",
            headers={"Origin": "https://evil.example"},
        )
        assert response.headers.get("access-control-allow-origin") != "https://evil.example"


class TestNoSecretsInTheRepository:
    def test_dotenv_is_not_tracked(self):
        import subprocess

        tracked = subprocess.run(
            ["git", "ls-files", ".env"], capture_output=True, text=True, check=False
        )
        assert tracked.stdout.strip() == "", ".env must never be committed"

    def test_env_example_carries_no_credential(self):
        from pathlib import Path

        example = (
            Path(__file__).resolve().parents[2] / ".env.example"
        ).read_text(encoding="utf-8")
        assert "replace_me" in example
        # A key-shaped value would make the example a credential in waiting.
        assert "API_KEY_LU" not in example
        assert "postgresql+psycopg://postgres:ramen" not in example
