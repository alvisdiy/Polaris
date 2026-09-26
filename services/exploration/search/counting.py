"""CountingSearchProvider — exact search-query accounting.

Search queries are issued from more than one place in a run: the web-search
surface (discovery) and authority resolution (per-opportunity follow-up). Run
metrics must report how many queries were actually sent to the backend, so the
count is taken at the provider boundary instead of being tallied separately at
every call site, where it silently drifts.
"""

from __future__ import annotations

from services.exploration.search.base import SearchProvider, SearchQuery, SearchResult


class CountingSearchProvider(SearchProvider):
    """Delegating wrapper that counts calls, failures and received results."""

    def __init__(self, inner: SearchProvider) -> None:
        self.inner = inner
        self.calls = 0
        self.failures = 0
        self.results = 0

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.inner.name

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.calls += 1
        try:
            results = await self.inner.search(query)
        except Exception:  # noqa: BLE001 - counted, then handled by the caller
            self.failures += 1
            raise
        self.results += len(results)
        return results
