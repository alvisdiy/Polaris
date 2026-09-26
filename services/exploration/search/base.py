"""SearchProvider abstraction.

The core exploration engine depends only on this interface; the concrete
search backend is replaceable by configuration. The engine never knows which
provider is active.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SearchQuery:
    text: str
    country_iso2: str = ""
    locale: str = ""
    gl: str = ""
    result_count: int = 10
    family: str = ""


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str = ""
    position: int = 0
    provider_name: str = ""
    metadata: dict = field(default_factory=dict)


class SearchProvider(abc.ABC):
    """Replaceable web search backend."""

    name: str = "abstract"

    @abc.abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Execute a web search and return organic results.

        Implementations must raise on unrecoverable errors so callers can
        apply their own degradation policy.
        """
        ...
