"""robots.txt handling in the discovery analyzer.

The analyzer's own scanner used to implement a subset of robots.txt: only
``Disallow`` inside a ``User-agent: *`` group, no ``Allow``, and a prefix match
that turned ``Disallow: /`` into a blanket ban even where ``Allow: /en/`` was
declared. A published site with that ordinary shape became undiscoverable, and
because a robots rejection is a *permanent* fetch error the loss survived
later runs.
"""

from __future__ import annotations

import pytest

from services.exploration import candidate_analyzer
from services.exploration.candidate_analyzer import USER_AGENT, _RobotRules


class _Response:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text


class _Client:
    def __init__(self, *, body: str = "", status_code: int = 200, error: Exception | None = None):
        self.body = body
        self.status_code = status_code
        self.error = error
        self.calls = 0

    async def get(self, url: str):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return _Response(self.status_code, self.body)


@pytest.fixture(autouse=True)
def clear_robots_cache():
    candidate_analyzer._robots_cache.clear()
    yield
    candidate_analyzer._robots_cache.clear()


class TestAllowDirectives:
    @pytest.mark.asyncio
    async def test_allow_beats_a_shorter_disallow(self):
        body = "User-agent: *\nDisallow: /\nAllow: /en/\n"
        client = _Client(body=body)

        assert await _RobotRules.allowed(client, "https://example.org/en/scholarships") is True
        assert await _RobotRules.allowed(client, "https://example.org/admin") is False

    @pytest.mark.asyncio
    async def test_disallow_prefix_still_applies(self):
        body = "User-agent: *\nDisallow: /search\n"
        client = _Client(body=body)

        assert await _RobotRules.allowed(client, "https://example.org/search/results") is False
        assert await _RobotRules.allowed(client, "https://example.org/scholarships") is True


class TestUserAgentGroups:
    @pytest.mark.asyncio
    async def test_a_group_for_another_crawler_does_not_apply(self):
        body = (
            "User-agent: Googlebot\n"
            "Disallow: /\n"
            "\n"
            "User-agent: *\n"
            "Allow: /\n"
        )
        client = _Client(body=body)

        assert await _RobotRules.allowed(client, "https://example.org/scholarships") is True

    @pytest.mark.asyncio
    async def test_the_named_group_applies_to_our_agent(self):
        body = (
            f"User-agent: {USER_AGENT.split('/')[0]}\n"
            "Disallow: /private\n"
            "\n"
            "User-agent: *\n"
            "Allow: /\n"
        )
        client = _Client(body=body)

        assert await _RobotRules.allowed(client, "https://example.org/private/x") is False
        assert await _RobotRules.allowed(client, "https://example.org/public") is True


class TestAbsenceAndErrors:
    @pytest.mark.asyncio
    async def test_missing_robots_txt_allows_the_fetch(self):
        client = _Client(status_code=404)

        assert await _RobotRules.allowed(client, "https://example.org/scholarships") is True

    @pytest.mark.asyncio
    async def test_unreachable_robots_txt_allows_the_fetch(self):
        client = _Client(error=RuntimeError("connection refused"))

        assert await _RobotRules.allowed(client, "https://example.org/scholarships") is True

    @pytest.mark.asyncio
    async def test_robots_is_fetched_once_per_origin(self):
        client = _Client(body="User-agent: *\nAllow: /\n")

        assert await _RobotRules.allowed(client, "https://example.org/a") is True
        assert await _RobotRules.allowed(client, "https://example.org/b") is True
        assert client.calls == 1
