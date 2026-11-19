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
        self.failure_categories: dict[str, int] = {}

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.inner.name

    @property
    def configured(self) -> bool:
        """Expose optional backend configuration without knowing its type."""
        return bool(getattr(self.inner, "configured", True))

    @staticmethod
    def _failure_category(exc: Exception) -> str:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code is not None:
            return f"http_{int(status_code)}"
        if "timeout" in type(exc).__name__.casefold():
            return "timeout"
        if isinstance(exc, RuntimeError) and "not configured" in str(exc).casefold():
            return "unconfigured"
        return type(exc).__name__.casefold()

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        self.calls += 1
        try:
            results = await self.inner.search(query)
        except Exception as exc:  # noqa: BLE001 - counted, then handled by the caller
            self.failures += 1
            category = self._failure_category(exc)
            self.failure_categories[category] = self.failure_categories.get(category, 0) + 1
            raise
        self.results += len(results)
        return results
