"""The web-search surface: query families and honest failure accounting."""

from __future__ import annotations

import uuid

import pytest

from services.exploration.query_generation import PlannedQuery
from services.exploration.search.base import SearchResult
from services.exploration.surfaces.web_search import WebSearchSurface


class _Provider:
    name = "fake"
    configured = True

    def __init__(self, results=None, error: Exception | None = None):
        self._results = results or []
        self._error = error
        self.queries: list[str] = []

    async def search(self, query):
        self.queries.append(query.text)
        if self._error is not None:
            raise self._error
        return self._results


class _Frontier:
    def __init__(self):
        self.rows: list[tuple[str, dict]] = []

    def upsert_candidate(self, country_id, url, **kwargs):
        self.rows.append((url, kwargs))
        return object(), True


def _plan(*families: str) -> list[PlannedQuery]:
    return [
        PlannedQuery(text=f"query-{family}", family=family, candidate_type_hint="opportunity")
        for family in families
    ]


class TestPriorityMapping:
    def test_new_families_are_not_buried_at_the_default(self):
        """`funding`, `degree` and `ecosystem` used to fall through to 5.

        Lower runs first, so the queries added to widen discovery were
        processed behind everything the original four already covered.
        """
        priorities = {
            family: WebSearchSurface._priority_for(
                PlannedQuery(text="q", family=family, candidate_type_hint="opportunity")
            )
            for family in (
                "opportunity",
                "funding",
                "degree",
                "ecosystem",
                "provider",
                "official_source",
                "localized",
                "unknown_family",
            )
        }
        assert priorities["opportunity"] == 2
        assert priorities["funding"] == 3
        assert priorities["degree"] == 3
        assert priorities["ecosystem"] == 3
        assert priorities["provider"] == 3
        assert priorities["official_source"] == 3
        assert priorities["localized"] == 4
        assert priorities["unknown_family"] == 5
        assert all(value < 5 for family, value in priorities.items() if family != "unknown_family")


class TestExecute:
    @pytest.mark.asyncio
    async def test_an_empty_result_set_is_not_a_degraded_run(self):
        frontier = _Frontier()
        surface = WebSearchSurface(_Provider(results=[]))

        outcome = await surface.execute(
            _plan("funding", "degree"),
            uuid.uuid4(),
            "JP",
            "ja-JP",
            "jp",
            frontier,
        )

        assert outcome.queries_executed == 2
        assert outcome.queries_failed == 0
        assert outcome.results_received == 0
        assert outcome.candidates_created == 0
        assert outcome.degraded_reason is None
        assert frontier.rows == []

    @pytest.mark.asyncio
    async def test_aggregator_results_are_skipped_at_admission(self):
        """A listing site is a lead, not an official source. Do not queue it."""
        frontier = _Frontier()
        provider = _Provider(
            results=[
                SearchResult(url="https://www.wemakescholars.com/x", title="Aggregator"),
                SearchResult(
                    url="https://www.studyinjapan.go.jp/en/scholarship/",
                    title="Official",
                ),
            ]
        )

        outcome = await WebSearchSurface(provider).execute(
            _plan("opportunity"), uuid.uuid4(), "JP", "ja-JP", "jp", frontier
        )

        assert outcome.results_received == 2
        assert outcome.candidates_created == 1
        assert outcome.skipped_aggregators == 1
        assert [url for url, _ in frontier.rows] == [
            "https://www.studyinjapan.go.jp/en/scholarship/"
        ]

    @pytest.mark.asyncio
    async def test_a_provider_exception_is_a_failed_query(self):
        frontier = _Frontier()
        surface = WebSearchSurface(_Provider(error=RuntimeError("blocked")))

        outcome = await surface.execute(
            _plan("opportunity"),
            uuid.uuid4(),
            "JP",
            "ja-JP",
            "jp",
            frontier,
        )

        assert outcome.queries_executed == 0
        assert outcome.queries_failed == 1
        assert outcome.degraded_reason == "all search queries failed"

    @pytest.mark.asyncio
    async def test_unconfigured_provider_short_circuits(self):
        class _Unconfigured(_Provider):
            configured = False

        outcome = await WebSearchSurface(_Unconfigured()).execute(
            _plan("opportunity"),
            uuid.uuid4(),
            "JP",
            "ja-JP",
            "jp",
            _Frontier(),
        )

        assert outcome.queries_executed == 0
        assert "not configured" in (outcome.degraded_reason or "")
