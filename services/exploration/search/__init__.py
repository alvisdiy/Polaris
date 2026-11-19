"""SearchProvider implementations and selection factory.

The engine depends only on SearchProvider. Selection is by env var:
POLARIS_SEARCH_PROVIDER (default: ddgs). Adding a new provider later means
adding one adapter module + one registry entry here.
"""

from __future__ import annotations

import os

from services.exploration.search.base import SearchProvider, SearchQuery, SearchResult
from services.exploration.search.ddgs import DDGSearchProvider
from services.exploration.search.null_provider import NullSearchProvider
from services.exploration.search.serper import SerperSearchProvider

__all__ = [
    "SearchProvider",
    "SearchQuery",
    "SearchResult",
    "NullSearchProvider",
    "SerperSearchProvider",
    "DDGSearchProvider",
    "create_search_provider",
]


def create_search_provider(timeout: int = 15, max_results: int = 10) -> SearchProvider:
    """Instantiate the configured search provider from the environment.

    Supported providers:

    - ``null`` — no-op provider for tests and dry runs.
    - ``serper`` — Serper.dev Google search (requires POLARIS_SERPER_API_KEY).
    - ``ddgs`` — free DuckDuckGo-based metasearch via the ``ddgs`` library.
    """
    name = os.getenv("POLARIS_SEARCH_PROVIDER", "ddgs").strip().lower()
    if name == "null":
        return NullSearchProvider()
    if name == "serper":
        return SerperSearchProvider(timeout=timeout)
    if name == "ddgs":
        return DDGSearchProvider(timeout=timeout, max_results=max_results)
    raise ValueError(
        f"Unknown POLARIS_SEARCH_PROVIDER '{name}'. Supported: serper, null, ddgs"
    )
