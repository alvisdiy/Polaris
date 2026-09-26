"""WebSearchSurface — primary internet discovery.

Country → QueryGenerator → SearchProvider → SearchResults → Frontier
candidates with full search provenance (query, provider, rank, snippet).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger

from services.exploration.query_generation import PlannedQuery
from services.exploration.repositories.frontier_repository import (
    FrontierObservation,
    FrontierRepository,
)
from services.exploration.search.base import SearchProvider, SearchQuery

if TYPE_CHECKING:
    from uuid import UUID


class SurfaceOutcome:
    def __init__(self) -> None:
        self.queries_executed = 0
        self.queries_failed = 0
        self.results_received = 0
        self.candidates_created = 0
        self.degraded_reason: str | None = None


class WebSearchSurface:
    """Executes the generated query plan through the SearchProvider."""

    def __init__(self, provider: SearchProvider) -> None:
        self.provider = provider

    async def execute(
        self,
        plan: list[PlannedQuery],
        country_id: "UUID",
        country_iso2: str,
        locale: str,
        gl: str,
        frontier: FrontierRepository,
        run_id: "UUID | None" = None,
        results_per_query: int = 10,
    ) -> SurfaceOutcome:
        outcome = SurfaceOutcome()
        now = datetime.now(timezone.utc).isoformat()

        if isinstance(self.provider, type(self)) and not getattr(self.provider, "configured", True):
            outcome.degraded_reason = "search provider not configured"
            return outcome

        for planned in plan:
            query = SearchQuery(
                text=planned.text,
                country_iso2=country_iso2,
                locale=locale,
                gl=gl,
                result_count=results_per_query,
                family=planned.family,
            )
            try:
                results = await self.provider.search(query)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Search query failed ({}): {}", planned.family, exc)
                outcome.queries_failed += 1
                continue

            outcome.queries_executed += 1
            outcome.results_received += len(results)

            for result in results:
                observation = FrontierObservation(
                    origin="web_search",
                    origin_query=planned.text,
                    search_provider=self.provider.name,
                    rank=result.position,
                    snippet=result.snippet[:500] if result.snippet else None,
                    title=result.title[:300] if result.title else None,
                    run_id=str(run_id) if run_id else None,
                    at=now,
                )
                candidate, created = frontier.upsert_candidate(
                    country_id,
                    result.url,
                    origin="web_search",
                    candidate_type=planned.candidate_type_hint,
                    origin_query=planned.text,
                    observation=observation,
                    priority=self._priority_for(planned),
                    run_id=run_id,
                )
                if created:
                    outcome.candidates_created += 1

        if outcome.queries_executed == 0 and outcome.queries_failed > 0:
            outcome.degraded_reason = "all search queries failed"

        logger.info(
            "WebSearchSurface: {} queries, {} results, {} new candidates",
            outcome.queries_executed,
            outcome.results_received,
            outcome.candidates_created,
        )
        return outcome

    @staticmethod
    def _priority_for(planned: PlannedQuery) -> int:
        return {
            "opportunity": 2,
            "provider": 3,
            "official_source": 3,
            "localized": 4,
        }.get(planned.family, 5)
