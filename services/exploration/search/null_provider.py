"""NullSearchProvider — records queries, returns no results.

Used by unit/integration tests, --dry-run mode, and as the safe fallback when
no real search provider is configured. Keeps the engine fully exercisable
without live internet access.
"""

from __future__ import annotations

from services.exploration.search.base import SearchProvider, SearchQuery, SearchResult


class NullSearchProvider(SearchProvider):
    name = "null"

    def __init__(self) -> None:
        self.calls: list[SearchQuery] = []

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.calls.append(query)
        return []
