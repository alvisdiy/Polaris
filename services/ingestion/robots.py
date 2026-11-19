"""robots.txt policy for outbound crawling.

The policy is explicit rather than implicit: a named user agent, a per-host
cache, and defined behaviour for the three cases that actually occur —
allowed, disallowed, and "there is no robots.txt".

    DISALLOWED -> do not fetch, record why
    ALLOWED    -> fetch
    ABSENT     -> fetch (a site with no robots.txt has not forbidden anything)
    ERROR      -> fetch, and say so once (a 500 on robots.txt is the site's
                  problem, not a licence to stop collecting its public pages)

Enabled by default. Turning it off is a deliberate act, not a config default,
because "we never checked" is the outcome nobody wants to discover later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from services.exploration.robots_rules import RobotsRules

logger = logging.getLogger("polaris.ingestion.robots")

DEFAULT_USER_AGENT = "PolarisBot/0.1 (scholarship research; +https://polaris.example/bot)"


@dataclass
class RobotsDecision:
    allowed: bool
    reason: str
    robots_status: str  # ALLOWED (readable) | ABSENT | ERROR | DISABLED


@dataclass
class RobotsPolicy:
    """Fetch, cache and apply robots.txt for the hosts Polaris visits.

    `fetch_robots` is injected so tests (and offline runs) can supply robots
    bodies without touching the network.
    """

    user_agent: str = DEFAULT_USER_AGENT
    enabled: bool = True
    fetch_robots: object = None  # async (url) -> str | None
    _cache: dict[str, RobotsRules | None] = field(default_factory=dict, repr=False)
    _status: dict[str, str] = field(default_factory=dict, repr=False)

    async def can_fetch(self, url: str) -> RobotsDecision:
        if not self.enabled:
            return RobotsDecision(True, "robots policy disabled", "DISABLED")
        rules, status = await self._parser_for(url)
        if rules is None:
            return RobotsDecision(True, f"no robots.txt to consult ({status})", status)
        if rules.allows(self.user_agent, url):
            return RobotsDecision(True, "allowed by robots.txt", status)
        return RobotsDecision(False, "disallowed by robots.txt", status)

    async def _parser_for(self, url: str) -> tuple[RobotsRules | None, str]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._cache:
            return self._cache[origin], self._status.get(origin, "ABSENT")

        rules: RobotsRules | None = None
        status = "ABSENT"
        try:
            body = await self._load(f"{origin}/robots.txt")
            if body is None:
                status = "ABSENT"
                rules = None
            else:
                rules = RobotsRules.from_text(body)
                status = "ALLOWED"
        except Exception as exc:  # network, robots.txt served as HTML, ...
            # A site whose robots.txt 500s has not forbidden crawling, and
            # failing closed here would silently stop collection everywhere.
            logger.warning("robots.txt unavailable for %s: %s", origin, exc)
            status = "ERROR"
            rules = None

        self._cache[origin] = rules
        self._status[origin] = status
        return rules, status

    async def _load(self, robots_url: str) -> str | None:
        if self.fetch_robots is not None:
            return await self.fetch_robots(robots_url)
        return await _http_get(robots_url, self.user_agent)


async def _http_get(url: str, user_agent: str) -> str | None:
    """Default loader: a plain GET, returning None for 4xx.

    Goes through the same URL safety boundary as any other request.
    """
    import httpx

    from services.ingestion.url_safety import UrlSafetyError, validate_external_url

    try:
        validate_external_url(url, resolve_dns=True)
    except UrlSafetyError as exc:
        logger.warning("refusing to fetch robots.txt: %s", exc)
        return None

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": user_agent})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
