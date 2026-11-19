"""Outbound HTTP, with every safety rule applied in one place.

A connector that calls ``client.get(url)`` directly gets none of it. This is
the door every request goes through instead:

    1. robots.txt says we may fetch this path
    2. the URL is a public target, and so is every address it resolves to
    3. transient failures are retried, boundedly, with backoff
    4. every redirect hop is re-validated — the server's chosen target is as
       untrusted as the URL a human typed

Keeping the four together matters: each one alone has a hole the other three
close. Retry without a bounded budget is a request storm; robots without URL
validation still allows ``Disallow: /`` from a private address; validating only
the first hop of a redirect chain is the classic SSRF bypass.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

import httpx

from services.ingestion.robots import RobotsDecision, RobotsPolicy
from services.ingestion.url_safety import (
    UrlSafetyError,
    validate_external_url,
    validate_redirect_chain,
)

logger = logging.getLogger("polaris.ingestion.fetch_safety")

# Retrying a 4xx (other than 429) repeats a request the server has already
# answered definitively: 404 will stay 404, 401 will stay 401.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

MAX_BACKOFF_SECONDS = 60.0


class RobotsDisallowed(Exception):
    """robots.txt forbids this path for our user agent."""


class SafeFetch:
    """Performs one guarded GET with bounded retry.

    Config values (`max_retries`, `backoff_factor`) come from the existing
    `ConnectorConfig`, which declared them long before anything read them.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        robots: RobotsPolicy | None = None,
        allow_http: bool = True,
        resolve_dns: bool = True,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.max_retries = max(0, int(max_retries))
        self.backoff_factor = max(1.0, float(backoff_factor))
        self.robots = robots
        self.allow_http = allow_http
        self.resolve_dns = resolve_dns
        self._sleep = sleep

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Fetch `url`, or raise.

        Raises:
            UrlSafetyError: the target is not a public address.
            RobotsDisallowed: robots.txt forbids this path.
            httpx.HTTPStatusError: a permanent failure after the retries.
        """
        target = validate_external_url(
            url, allow_http=self.allow_http, resolve_dns=self.resolve_dns
        )

        if self.robots is not None:
            decision: RobotsDecision = await self.robots.can_fetch(target)
            if not decision.allowed:
                logger.info("robots.txt refused %s: %s", target, decision.reason)
                raise RobotsDisallowed(f"{target}: {decision.reason}")

        response = await self._get_with_retry(target, **kwargs)
        self._check_chain(response)
        return response

    async def _get_with_retry(self, url: str, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            try:
                response = await self.client.get(url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_retries:
                    raise
                delay = self._delay(attempt, None)
                logger.warning(
                    "fetch failed (%s); retry %d/%d in %.1fs",
                    exc.__class__.__name__, attempt + 1, self.max_retries, delay,
                )
                attempt += 1
                await self._sleep(delay)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                delay = self._delay(attempt, response)
                logger.warning(
                    "HTTP %s for %s; retry %d/%d in %.1fs",
                    response.status_code, url, attempt + 1, self.max_retries, delay,
                )
                attempt += 1
                await self._sleep(delay)
                continue

            response.raise_for_status()
            return response

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Exponential backoff, honouring Retry-After when the server sent one."""
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return min(MAX_BACKOFF_SECONDS, float(retry_after))
                except ValueError:
                    pass
        return min(MAX_BACKOFF_SECONDS, self.backoff_factor ** attempt)

    @staticmethod
    def _check_chain(response: httpx.Response) -> None:
        """Re-validate the whole redirect chain, including the final URL.

        Validation happens after the request because httpx follows redirects
        itself: the hop was already made by the time we see it. That is why
        this is a hard failure rather than a warning — a chain that crossed
        into private space has already crossed, and the response must not be
        used for extraction.
        """
        try:
            history = [str(item.url) for item in response.history]
            validate_redirect_chain(str(response.url), history)
        except UrlSafetyError as exc:
            raise UrlSafetyError(
                f"redirect chain left the public internet: {exc}"
            ) from None
