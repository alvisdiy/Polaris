"""DuckDuckGo-based search provider for Polaris discovery.

Uses the free `ddgs` library as a metasearch backend for text search.
No API key is required to attempt a search, but results are provided by
upstream engines and may be unavailable, throttled, or blocked at any time.

This provider does **not** bypass CAPTCHAs, authentication, paywalls, or
other access controls. If upstream services block a request, the provider
raises an error and the exploration surface degrades as usual.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

from services.exploration.search.base import SearchProvider, SearchQuery, SearchResult

logger = logger.bind(provider="ddgs")

# Truncation budget for title/snippet. Upstream occasionally returns very long
# blobs (press releases pasted into a snippet field); the frontier stores at
# most 500 chars of snippet and 300 of title anyway.
_SNIPPET_BUDGET = 2000


def _ddgs_client(timeout: int):
    """Build a real DDGS client.

    Kept as a module-level function (import stays inside the body) so the
    `ddgs` package remains an optional dependency: the rest of the search
    stack imports and runs without it, and unit tests shadow this one seam
    instead of the network.
    """
    from ddgs import DDGS

    return DDGS(timeout=timeout)


class DDGSearchProvider(SearchProvider):
    """Free text search via the `ddgs` library.

    It is a replaceable SearchProvider implementation, not a new search
    framework. The exploration engine sees only the SearchProvider interface.
    """

    name = "ddgs"

    def __init__(self, timeout: int = 15, max_results: int = 10) -> None:
        self._timeout = timeout
        # ddgs itself accepts any page size, but one query should not try to
        # pull a whole SERP: the engine deduplicates across queries anyway.
        self._max_results = max(1, min(max_results, 20))
        self._executor: ThreadPoolExecutor | None = None

    def _run_text(self, query: SearchQuery) -> list[dict[str, Any]]:
        from ddgs.ddgs import DDGSException, TimeoutException

        ddgs = _ddgs_client(self._timeout)
        try:
            return ddgs.text(
                query.text,
                max_results=self._max_results,
                region=self._region_for(query),
                safesearch="moderate",
                page=1,
            )
        except TimeoutException as exc:
            # Subclass of DDGSException — must be caught first.
            raise TimeoutError(str(exc)) from exc
        except DDGSException as exc:
            # "No results found." is an answer, not a failure: the backend
            # worked and this query has nothing. Reporting it as a failed
            # query inflated `queries_failed` and flipped a whole run to
            # "degraded" whenever a long-tail query simply had no matches.
            # Rate limits and upstream blocks still raise.
            if _is_no_results(exc):
                return []
            raise RuntimeError(str(exc)) from exc

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        if not query.text.strip():
            return []

        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ddgs")

        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                self._executor,
                self._run_text,
                query,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("DDGS search failed: {}", exc)
            raise

        if not raw:
            # A backend that returns an empty list is answering "nothing for
            # this query", not failing. Only an exception means failure.
            return []

        return _normalize_results(raw)

    @staticmethod
    def _region_for(query: SearchQuery) -> str:
        """Map Polaris (gl/country/locale) onto a ddgs region code.

        ddgs regions are ``{country}-{lang}`` (its own default is ``us-en``).
        ``gl`` wins over ``country_iso2``; the locale's language overrides the
        default ``en`` when present.
        """
        if query.gl:
            base = query.gl.lower()
        elif query.country_iso2:
            base = query.country_iso2.lower()
        else:
            base = "us"
        lang = "en"
        if query.locale:
            parts = query.locale.split("-", 1)
            if len(parts) == 2:
                lang = parts[0].lower()
                base = parts[1].lower()
            else:
                lang = query.locale.lower()
        return f"{base}-{lang}"


def _normalize_results(items: list[dict[str, Any]]) -> list[SearchResult]:
    out: list[SearchResult] = []
    seen: set[str] = set()

    for position, item in enumerate(items, start=1):
        url = _pick_url(item)
        if not url or url in seen:
            continue
        seen.add(url)

        out.append(
            SearchResult(
                url=url,
                title=_pick_str(item.get("title")),
                snippet=_pick_str(item.get("body") or item.get("snippet")),
                position=position,
                provider_name="ddgs",
                metadata={
                    "source": _pick_str(item.get("source")),
                    "raw": {
                        k: v
                        for k, v in item.items()
                        if k not in ("url", "title", "body", "snippet", "source")
                    },
                },
            )
        )

    return out


def _is_no_results(exc: Exception) -> bool:
    """Whether an upstream exception means "this query has no matches".

    The `ddgs` library signals an empty SERP with a DDGSException whose text
    is "No results found." Counting that as a backend failure makes ordinary
    long-tail queries look like outages.
    """
    return "no results" in str(exc).casefold()


def _pick_url(item: dict[str, Any]) -> str:
    for key in ("href", "url", "embed_url", "link"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _pick_str(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if len(text) > _SNIPPET_BUDGET:
        text = text[:_SNIPPET_BUDGET].rstrip()
    return text
