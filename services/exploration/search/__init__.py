"""SearchProvider implementations and selection factory.

The engine depends only on SearchProvider. Selection is by env var:
POLARIS_SEARCH_PROVIDER (default: serper). Adding a new provider later means
adding one adapter module + one registry entry here.
"""

from __future__ import annotations

import os

from services.exploration.search.base import SearchProvider, SearchQuery, SearchResult
from services.exploration.search.null_provider import NullSearchProvider
from services.exploration.search.serper import SerperSearchProvider

__all__ = [
    "SearchProvider",
    "SearchQuery",
    "SearchResult",
    "NullSearchProvider",
    "SerperSearchProvider",
    "create_search_provider",
]


def create_search_provider(timeout: int = 15) -> SearchProvider:
    """Instantiate the configured search provider from the environment."""
    name = os.getenv("POLARIS_SEARCH_PROVIDER", "serper").strip().lower()
    if name == "null":
        return NullSearchProvider()
    if name == "serper":
        return SerperSearchProvider(timeout=timeout)
    raise ValueError(
        f"Unknown POLARIS_SEARCH_PROVIDER '{name}'. Supported: serper, null"
    )
