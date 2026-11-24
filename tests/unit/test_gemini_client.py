"""Gemini client behaviour, exercised through a fake transport.

The free tier is the design constraint: throttling must happen
client-side, 429s must back off and then give up as LLMUnavailable
(never as a crash), and a malformed reply must never reach the
extraction layer as data.
"""

from __future__ import annotations

import json

import httpx
import pytest

from services.intelligence.gemini import GeminiClient, LLMUnavailable, gemini_from_env


def _response(status: int, body) -> httpx.Response:
    return httpx.Response(
        status,
        content=body if isinstance(body, bytes) else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )


def _ok_payload(obj) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}]}


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(post, clock: FakeClock, **kwargs) -> GeminiClient:
    return GeminiClient(
        "test-key",
        min_interval_seconds=4.0,
        post=post,
        sleep=clock.sleep,
        clock=clock.time,
        **kwargs,
    )


class TestGenerateJson:
    def test_returns_the_parsed_object_and_sends_the_key(self):
        seen = {}

        def post(url, json=None, headers=None, timeout=None):
            seen.update(url=url, headers=headers, payload=json)
            return _response(200, _ok_payload({"deadline": {"value": "2027-03-01"}}))

        clock = FakeClock()
        client = _client(post, clock)
        result = client.generate_json("prompt")
        assert result == {"deadline": {"value": "2027-03-01"}}
        assert seen["headers"]["x-goog-api-key"] == "test-key"
        assert "gemini-2.5-flash" in seen["url"]
        assert seen["payload"]["generationConfig"]["responseMimeType"] == "application/json"

    def test_throttles_the_second_call(self):
        clock = FakeClock()

        def post(url, json=None, headers=None, timeout=None):
            return _response(200, _ok_payload({}))

        client = _client(post, clock)
        client.generate_json("a")
        client.generate_json("b")
        assert clock.sleeps and clock.sleeps[0] == pytest.approx(4.0)

    def test_retries_a_429_then_succeeds(self):
        clock = FakeClock()
        attempts = {"n": 0}

        def post(url, json=None, headers=None, timeout=None):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return _response(429, {"error": {"message": "quota"}})
            return _response(200, _ok_payload({"ok": True}))

        client = _client(post, clock)
        assert client.generate_json("x") == {"ok": True}
        assert attempts["n"] == 2

    def test_quota_exhaustion_is_unavailable_not_a_crash(self):
        clock = FakeClock()

        def post(url, json=None, headers=None, timeout=None):
            return _response(429, {"error": {"message": "quota"}})

        client = _client(post, clock)
        with pytest.raises(LLMUnavailable):
            client.generate_json("x")

    def test_non_json_reply_is_unavailable(self):
        clock = FakeClock()

        def post(url, json=None, headers=None, timeout=None):
            return _response(200, {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})

        client = _client(post, clock)
        with pytest.raises(LLMUnavailable):
            client.generate_json("x")

    def test_a_client_error_does_not_retry(self):
        clock = FakeClock()
        attempts = {"n": 0}

        def post(url, json=None, headers=None, timeout=None):
            attempts["n"] += 1
            return _response(400, {"error": {"message": "bad request"}})

        client = _client(post, clock)
        with pytest.raises(LLMUnavailable):
            client.generate_json("x")
        assert attempts["n"] == 1


class TestFromEnv:
    def test_no_key_means_no_client(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("POLARIS_LLM_API_KEY", raising=False)
        assert gemini_from_env() is None

    def test_key_builds_a_client(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "abc")
        assert gemini_from_env() is not None
