"""Security boundary tests: URL validation, SSRF, robots, retry, redirects.

M10 Phase 1. These are not "should behave nicely" tests. Each one asserts that
a specific request does **not** happen, because the failure mode they guard —
reaching an internal service, or trusting a redirect that leaves the public
internet — is invisible in a passing pipeline and catastrophic in production.
"""

from __future__ import annotations

import httpx
import pytest

from services.ingestion.fetch_safety import (
    RETRYABLE_STATUS,
    RobotsDisallowed,
    SafeFetch,
)
from services.ingestion.robots import RobotsPolicy
from services.ingestion.url_safety import (
    UrlSafetyError,
    is_safe_url,
    validate_external_url,
    validate_redirect_chain,
)

# Every one of these must be refused. The list is the threat model written out.
DANGEROUS_URLS = [
    "javascript:alert(1)",
    "JavaScript:alert(document.cookie)",
    "file:///etc/passwd",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "ftp://example.org/scholarships.txt",
    "gopher://example.org/",
    "http://localhost/",
    "http://localhost:5432/",
    "https://sub.localhost/admin",
    "http://127.0.0.1/",
    "http://127.0.0.1:9200/_cluster/health",
    "http://127.1/",
    "http://0.0.0.0/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://10.0.0.5/",
    "http://172.16.31.9/",
    "http://192.168.1.1/admin",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://[fd00::1]/",
    "http://redis.internal/",
    "https://user:password@evil.example.org/",
    "http://example.org:99999/",
    "not-a-url",
    "",
]


class TestUrlValidation:
    @pytest.mark.parametrize("url", DANGEROUS_URLS)
    def test_dangerous_urls_are_refused(self, url):
        assert is_safe_url(url) is False, f"{url!r} should not be fetchable"

    def test_a_refusal_explains_itself(self):
        with pytest.raises(UrlSafetyError) as exc:
            validate_external_url("http://169.254.169.254/latest/meta-data/")
        assert "metadata" in str(exc.value)

    def test_normal_public_urls_pass(self):
        for url in (
            "https://www.studyinjapan.go.jp/en/",
            "https://www.tp.edu.sg/scholarships.html",
            "http://www.mfa.gov.sg/careers/",
            "https://example.org:8443/path?query=1#frag",
        ):
            assert is_safe_url(url) is True, url

    def test_http_can_be_refused_by_policy(self):
        """Downgrade control, separate from SSRF control."""
        assert is_safe_url("http://example.org/", allow_http=False) is False
        assert is_safe_url("https://example.org/", allow_http=False) is True

    def test_valid_url_is_returned_unchanged(self):
        url = "https://www.studyinjapan.go.jp/en/"
        assert validate_external_url(url) == url


class TestDnsResolution:
    """A hostname is not evidence of where the packet goes."""

    def test_a_public_name_that_resolves_private_is_refused(self, monkeypatch):
        import socket

        from services.ingestion import url_safety

        def fake_getaddrinfo(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)

        with pytest.raises(UrlSafetyError) as exc:
            url_safety.assert_public_dns("https://rebinding.example.org/")
        assert "loopback" in str(exc.value)

    def test_metadata_via_dns_is_refused(self, monkeypatch):
        import socket

        from services.ingestion import url_safety

        def fake_getaddrinfo(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)

        with pytest.raises(UrlSafetyError):
            url_safety.assert_public_dns("https://sneaky.example.org/latest/meta-data/")

    def test_a_public_resolution_passes(self, monkeypatch):
        import socket

        from services.ingestion import url_safety

        def fake_getaddrinfo(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)

        url_safety.assert_public_dns("https://www.studyinjapan.go.jp/en/")

    def test_unresolvable_is_not_treated_as_safe(self, monkeypatch):
        import socket

        from services.ingestion import url_safety

        def fake_getaddrinfo(host, port, **kwargs):
            raise socket.gaierror("Name or service not known")

        monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)

        with pytest.raises(UrlSafetyError):
            url_safety.assert_public_dns("https://does-not-exist.example/")


class TestRedirectChains:
    def test_a_redirect_into_private_space_is_refused(self):
        with pytest.raises(UrlSafetyError) as exc:
            validate_redirect_chain(
                "http://169.254.169.254/latest/meta-data/",
                ["https://www.example.org/scholarships"],
            )
        assert "metadata" in str(exc.value)

    async def test_safe_fetch_reports_a_chain_leaving_the_internet(self):
        """The fetch boundary names the failure in its own words."""
        hop = httpx.Response(
            301,
            request=httpx.Request("GET", "https://www.example.org/a"),
            headers={"location": "http://10.0.0.9/internal"},
        )
        final = _response("http://10.0.0.9/internal", history=[hop])
        client = _RecordingClient([final])
        safe = SafeFetch(client)

        with pytest.raises(UrlSafetyError) as exc:
            await safe.get("https://www.example.org/a")
        assert "public internet" in str(exc.value)

    def test_a_public_chain_passes(self):
        validate_redirect_chain(
            "https://www.example.org/en/",
            ["https://example.org/", "https://www.example.org/en/"],
        )

    def test_every_hop_is_checked_not_only_the_first(self):
        with pytest.raises(UrlSafetyError):
            validate_redirect_chain(
                "https://www.example.org/final",
                ["https://www.example.org/a", "http://10.0.0.9/internal"],
            )


def _response(url, *, history=(), status=200):
    return httpx.Response(
        status_code=status,
        request=httpx.Request("GET", url),
        history=list(history),
    )


class _RecordingClient:
    """Minimal httpx.AsyncClient stand-in that replays scripted responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestRobotsPolicy:
    async def test_disallowed_path_is_refused(self):
        async def fetch_robots(url):
            return "User-agent: *\nDisallow: /private/\n"

        policy = RobotsPolicy(fetch_robots=fetch_robots)
        decision = await policy.can_fetch("https://example.org/private/scholarship")
        assert decision.allowed is False
        # robots.txt itself was readable; it is the path that is refused.
        assert decision.robots_status == "ALLOWED"

    async def test_allowed_path_is_permitted(self):
        async def fetch_robots(url):
            return "User-agent: *\nDisallow: /private/\n"

        policy = RobotsPolicy(fetch_robots=fetch_robots)
        assert (await policy.can_fetch("https://example.org/scholarship")).allowed

    async def test_missing_robots_allows_the_fetch(self):
        async def fetch_robots(url):
            return None

        policy = RobotsPolicy(fetch_robots=fetch_robots)
        decision = await policy.can_fetch("https://example.org/scholarship")
        assert decision.allowed is True
        assert decision.robots_status == "ABSENT"

    async def test_broken_robots_allows_but_is_recorded(self):
        async def fetch_robots(url):
            raise RuntimeError("503 from robots.txt")

        policy = RobotsPolicy(fetch_robots=fetch_robots)
        decision = await policy.can_fetch("https://example.org/scholarship")
        assert decision.allowed is True
        assert decision.robots_status == "ERROR"

    async def test_robots_is_fetched_once_per_host(self):
        calls = []

        async def fetch_robots(url):
            calls.append(url)
            return "User-agent: *\nAllow: /\n"

        policy = RobotsPolicy(fetch_robots=fetch_robots)
        await policy.can_fetch("https://example.org/a")
        await policy.can_fetch("https://example.org/b")
        assert calls == ["https://example.org/robots.txt"]

    async def test_policy_can_be_disabled_explicitly(self):
        async def fetch_robots(url):
            return "User-agent: *\nDisallow: /\n"

        policy = RobotsPolicy(fetch_robots=fetch_robots, enabled=False)
        decision = await policy.can_fetch("https://example.org/a")
        assert decision.allowed is True
        assert decision.robots_status == "DISABLED"

    async def test_user_agent_is_explicit(self):
        from services.ingestion.robots import DEFAULT_USER_AGENT

        assert "PolarisBot" in DEFAULT_USER_AGENT
        assert RobotsPolicy().user_agent == DEFAULT_USER_AGENT


class TestSafeFetch:
    async def test_a_disallowed_url_is_never_requested(self):
        async def fetch_robots(url):
            return "User-agent: *\nDisallow: /\n"

        client = _RecordingClient([_response("https://example.org/")])
        safe = SafeFetch(client, robots=RobotsPolicy(fetch_robots=fetch_robots))

        with pytest.raises(RobotsDisallowed):
            await safe.get("https://example.org/scholarship")
        assert client.calls == []

    async def test_a_private_target_is_never_requested(self):
        client = _RecordingClient([])
        safe = SafeFetch(client)

        with pytest.raises(UrlSafetyError):
            await safe.get("http://169.254.169.254/latest/meta-data/")
        assert client.calls == []

    async def test_a_public_url_is_fetched_once(self):
        client = _RecordingClient([_response("https://example.org/scholarship")])
        safe = SafeFetch(client)
        response = await safe.get("https://example.org/scholarship")
        assert response.status_code == 200
        assert client.calls == ["https://example.org/scholarship"]


class TestRetryIsBounded:
    async def test_transient_failure_is_retried_then_succeeds(self):
        client = _RecordingClient(
            [
                httpx.ConnectError("connection reset"),
                _response("https://example.org/x", status=503),
                _response("https://example.org/x"),
            ]
        )
        slept: list[float] = []
        safe = SafeFetch(
            client,
            max_retries=3,
            backoff_factor=2.0,
            sleep=_record(slept),
        )

        response = await safe.get("https://example.org/x")

        assert response.status_code == 200
        assert len(client.calls) == 3
        assert slept == [1.0, 2.0]  # 2.0**0, 2.0**1

    async def test_retries_stop_at_the_configured_bound(self):
        client = _RecordingClient(
            [httpx.ConnectError("reset") for _ in range(10)]
        )
        slept: list[float] = []
        safe = SafeFetch(
            client, max_retries=2, backoff_factor=2.0, sleep=_record(slept)
        )

        with pytest.raises(httpx.ConnectError):
            await safe.get("https://example.org/x")
        assert len(client.calls) == 3  # the original plus two retries

    async def test_a_permanent_failure_is_not_retried(self):
        client = _RecordingClient([_response("https://example.org/x", status=404)])
        safe = SafeFetch(client, max_retries=3, sleep=_record([]))

        with pytest.raises(httpx.HTTPStatusError):
            await safe.get("https://example.org/x")
        assert len(client.calls) == 1

    def test_retryable_statuses_exclude_client_errors(self):
        assert 500 in RETRYABLE_STATUS
        assert 429 in RETRYABLE_STATUS
        assert 404 not in RETRYABLE_STATUS
        assert 401 not in RETRYABLE_STATUS

    async def test_retry_after_header_is_honoured(self):
        response = _response("https://example.org/x", status=429)
        response.headers["retry-after"] = "7"
        client = _RecordingClient([response, _response("https://example.org/x")])
        slept: list[float] = []
        safe = SafeFetch(client, max_retries=1, sleep=_record(slept))

        await safe.get("https://example.org/x")

        assert slept == [7.0]

    async def test_backoff_is_capped(self):
        client = _RecordingClient([_response("https://example.org/x", status=503)] * 8)
        slept: list[float] = []
        safe = SafeFetch(
            client, max_retries=6, backoff_factor=10.0, sleep=_record(slept)
        )

        with pytest.raises(httpx.HTTPStatusError):
            await safe.get("https://example.org/x")
        assert max(slept) <= 60.0


def _record(sink: list[float]):
    async def _sleep(seconds):
        sink.append(seconds)

    return _sleep
