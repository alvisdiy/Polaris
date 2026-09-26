"""Unit tests for the SearchProvider abstraction and adapters."""

import httpx
import pytest

from services.exploration.search import (
    NullSearchProvider,
    SearchQuery,
    SearchProvider,
    SearchResult,
    SerperSearchProvider,
    create_search_provider,
)
from services.exploration.search.counting import CountingSearchProvider


class TestNullProvider:
    @pytest.mark.asyncio
    async def test_returns_empty_and_records(self):
        provider = NullSearchProvider()
        q = SearchQuery(text="scholarships in Japan", country_iso2="JP")
        results = await provider.search(q)
        assert results == []
        assert provider.calls == [q]

    def test_is_a_search_provider(self):
        assert isinstance(NullSearchProvider(), SearchProvider)


class TestSerperProvider:
    def test_is_a_search_provider(self):
        assert isinstance(SerperSearchProvider(api_key="test"), SearchProvider)

    def test_not_configured_without_key(self, monkeypatch):
        monkeypatch.delenv("POLARIS_SERPER_API_KEY", raising=False)
        assert not SerperSearchProvider().configured

    def test_configured_with_key(self, monkeypatch):
        monkeypatch.setenv("POLARIS_SERPER_API_KEY", "abc")
        assert SerperSearchProvider().configured

    @pytest.mark.asyncio
    async def test_maps_organic_results(self, monkeypatch):
        captured = {}

        async def fake_post(self, url, **kwargs):
            captured["url"] = url
            captured["payload"] = kwargs.get("json")
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                request=request,
                json={
                    "organic": [
                        {"title": "Scholarships in Japan", "link": "https://a.example/x", "snippet": "study grants"},
                        {"title": "More", "link": "https://b.example/y", "snippet": ""},
                        {"title": "No link item", "link": ""},
                    ]
                },
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        provider = SerperSearchProvider(api_key="k")
        results = await provider.search(
            SearchQuery(text="scholarships in Japan", locale="ja-JP", gl="jp", result_count=10)
        )
        assert len(results) == 2  # linkless item dropped
        assert results[0].url == "https://a.example/x"
        assert results[0].position == 1
        assert results[1].position == 2
        assert captured["payload"]["hl"] == "ja-JP"
        assert captured["payload"]["gl"] == "jp"
        assert captured["payload"]["num"] == 10

    @pytest.mark.asyncio
    async def test_http_error_raises(self, monkeypatch):
        async def fake_post(self, url, **kwargs):
            return httpx.Response(429, request=httpx.Request("POST", url), json={})

        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
        provider = SerperSearchProvider(api_key="k")
        with pytest.raises(httpx.HTTPStatusError):
            await provider.search(SearchQuery(text="x"))

    @pytest.mark.asyncio
    async def test_unconfigured_raises(self, monkeypatch):
        monkeypatch.delenv("POLARIS_SERPER_API_KEY", raising=False)
        provider = SerperSearchProvider()
        with pytest.raises(RuntimeError):
            await provider.search(SearchQuery(text="x"))


class _RecordingProvider(SearchProvider):
    name = "recording"

    def __init__(self, results=None, raises=False):
        self.results = results or []
        self.raises = raises

    async def search(self, query):
        if self.raises:
            raise RuntimeError("backend down")
        return self.results


class TestCountingProvider:
    """Run metrics must reflect real backend calls, including failed ones."""

    def test_is_a_search_provider_and_delegates_name(self):
        counter = CountingSearchProvider(_RecordingProvider())
        assert isinstance(counter, SearchProvider)
        assert counter.name == "recording"

    @pytest.mark.asyncio
    async def test_counts_calls_and_results(self):
        counter = CountingSearchProvider(
            _RecordingProvider(results=[SearchResult(url="https://a.example", title="A")])
        )
        await counter.search(SearchQuery(text="q1"))
        await counter.search(SearchQuery(text="q2"))
        assert counter.calls == 2
        assert counter.results == 2
        assert counter.failures == 0

    @pytest.mark.asyncio
    async def test_failed_calls_counted_and_reraised(self):
        counter = CountingSearchProvider(_RecordingProvider(raises=True))
        with pytest.raises(RuntimeError):
            await counter.search(SearchQuery(text="q"))
        assert counter.calls == 1
        assert counter.failures == 1
        assert counter.results == 0


class TestFactory:
    def test_null_selection(self, monkeypatch):
        monkeypatch.setenv("POLARIS_SEARCH_PROVIDER", "null")
        assert isinstance(create_search_provider(), NullSearchProvider)

    def test_serper_default(self, monkeypatch):
        monkeypatch.delenv("POLARIS_SEARCH_PROVIDER", raising=False)
        assert isinstance(create_search_provider(), SerperSearchProvider)

    def test_unknown_provider_rejected(self, monkeypatch):
        monkeypatch.setenv("POLARIS_SEARCH_PROVIDER", "yahoo1999")
        with pytest.raises(ValueError):
            create_search_provider()
