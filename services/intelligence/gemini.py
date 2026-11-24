"""Gemini client for Google AI Studio (free tier), built for batch work.

The free tier is generous enough for nightly enrichment and far too
small for interactive use, so this client is designed around its
limits rather than despite them:

* a minimum interval between calls (default 4s, ~15 RPM) enforced
  client-side, so a batch slows itself down before Google has to;
* bounded retries with backoff on 429/5xx, then ``LLMUnavailable`` —
  callers treat an exhausted budget as "stop the LLM pass and report",
  never as a crash and never as a reason to invent data;
* one call carries every missing field for one record, so the call
  count scales with records, not fields;
* JSON mode (``responseMimeType: application/json``) with temperature
  0 — extraction is transcription, not creativity.

Configuration is environment-only: ``GEMINI_API_KEY`` (or
``POLARIS_LLM_API_KEY``), ``POLARIS_LLM_MODEL`` (default
``gemini-2.5-flash``, a free-tier Flash model), and
``POLARIS_LLM_MIN_INTERVAL_SECONDS``. With no key configured,
:func:`gemini_from_env` returns None and the LLM pass is simply off —
the deterministic pipeline is complete without it.
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable

import httpx

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_MIN_INTERVAL_SECONDS = 4.0


class LLMUnavailable(Exception):
    """The model cannot answer now (no key, quota, outage, bad reply).

    Callers must treat this as "no proposals from the LLM this run" —
    a normal outcome on a free quota, not an error in the data.
    """


class GeminiClient:
    """One-shot JSON generation against the AI Studio REST API.

    ``post``/``sleep``/``clock`` are injectable so tests exercise the
    throttling and retry logic without network or real waiting.
    """

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        post: Callable[..., httpx.Response] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            raise LLMUnavailable("no Gemini API key configured")
        self._api_key = api_key
        self._model = model
        self._min_interval = min_interval_seconds
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._post = post or httpx.post
        self._sleep = sleep
        self._clock = clock
        self._last_call_at: float | None = None
        self.calls_made = 0

    def _throttle(self) -> None:
        if self._last_call_at is None:
            return
        wait = self._min_interval - (self._clock() - self._last_call_at)
        if wait > 0:
            self._sleep(wait)

    def generate_json(self, prompt: str) -> dict:
        """Send one prompt and return the model's JSON object.

        Raises LLMUnavailable on quota exhaustion (after retries), on
        any non-200 response, and on a reply that is not a JSON object.
        """
        url = f"{API_ROOT}/models/{self._model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0,
            },
        }
        backoff = 10.0
        last_error = "no attempt made"
        for attempt in range(self._max_retries + 1):
            self._throttle()
            self._last_call_at = self._clock()
            self.calls_made += 1
            try:
                response = self._post(
                    url,
                    json=payload,
                    headers={"x-goog-api-key": self._api_key},
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
                response = None
            if response is not None:
                if response.status_code == 200:
                    return self._parse(response)
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code not in (429, 500, 502, 503):
                    break  # a 4xx other than 429 will not heal by retrying
            if attempt < self._max_retries:
                self._sleep(backoff)
                backoff *= 2
        raise LLMUnavailable(f"Gemini request failed after retries: {last_error}")

    @staticmethod
    def _parse(response: httpx.Response) -> dict:
        try:
            body = response.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"Gemini reply was not the expected JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMUnavailable("Gemini reply was JSON but not an object")
        return parsed


def gemini_from_env() -> GeminiClient | None:
    """The configured client, or None when no API key is set."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("POLARIS_LLM_API_KEY")
    if not api_key:
        return None
    model = os.getenv("POLARIS_LLM_MODEL", DEFAULT_MODEL)
    try:
        interval = float(
            os.getenv("POLARIS_LLM_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS)
        )
    except ValueError:
        interval = DEFAULT_MIN_INTERVAL_SECONDS
    return GeminiClient(api_key, model, min_interval_seconds=interval)
