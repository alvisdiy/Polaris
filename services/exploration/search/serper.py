"""Serper.dev search adapter — the one real SearchProvider shipped in v2.

Google search via the Serper.dev API. Credentials come from the environment
(POLARIS_SERPER_API_KEY); they are never hardcoded or stored in the database.
"""

from __future__ import annotations

import os

import httpx
from loguru import logger

from services.exploration.search.base import SearchProvider, SearchQuery, SearchResult

SERPER_ENDPOINT = "https://google.serper.dev/search"


class SerperSearchProvider(SearchProvider):
    name = "serper"

    def __init__(self, api_key: str | None = None, timeout: int = 15) -> None:
        self.api_key = api_key or os.getenv("POLARIS_SERPER_API_KEY", "")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        if not self.configured:
            raise RuntimeError(
                "SerperSearchProvider is not configured: set POLARIS_SERPER_API_KEY"
            )

        payload: dict = {
            "q": query.text,
            "num": max(1, min(query.result_count, 20)),
        }
        if query.locale:
            payload["hl"] = query.locale
        if query.gl:
            payload["gl"] = query.gl

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                SERPER_ENDPOINT,
                json=payload,
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()

        results: list[SearchResult] = []
        for position, item in enumerate(data.get("organic", []), start=1):
            url = item.get("link", "")
            if not url:
                continue
            results.append(
                SearchResult(
                    url=url,
                    title=item.get("title", "") or "",
                    snippet=item.get("snippet", "") or "",
                    position=position,
                    provider_name=self.name,
                    metadata={
                        "displayed_link": item.get("displayedLink", ""),
                        "date": item.get("date", ""),
                    },
                )
            )
        logger.debug("Serper '{}' → {} results", query.text, len(results))
        return results
