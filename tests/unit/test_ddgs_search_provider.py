"""Unit tests for the DDGS search provider.

Mock-based. No DuckDuckGo/Internet access required. The provider imports the
real library inside its own module, so tests shadow that import point rather
than the proxy object.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.exploration import search as _search_mod
from services.exploration.search import (
    DDGSearchProvider,
    SearchProvider,
    SearchQuery,
    create_search_provider,
)


def _item(url="https://example.org/scholarship", title="Scholarship", snippet="award"):
    return {"href": url, "title": title, "body": snippet}


class TestDDGSearchProviderIsAProvider:
    def test_implements_the_contract(self):
        provider = DDGSearchProvider()
        assert isinstance(provider, SearchProvider)
        assert provider.name == "ddgs"
        # The ddgs import stays lazy behind one module-level seam.
        assert callable(_search_mod.ddgs._ddgs_client)
        assert provider._executor is None


class TestDDGSearchProviderResultMapping:
    @pytest.mark.asyncio
    async def test_maps_title_url_and_body(self):
        provider = DDGSearchProvider(max_results=5)
        items = [
            _item(url="https://a.example/x", title="A Scholarship", snippet="fully funded"),
            _item(url="https://b.example/y", title="Another", snippet=""),
            _item(url="https://c.example/z", title="", snippet="no title"),
            _item(url="", title="no href"),
            _item(url="https://dup.example/d", title="Dup", snippet="same"),
            _item(url="https://dup.example/d", title="Dup again", snippet="same"),
        ]

        fake_ddgs = MagicMock(name="FakeDDGS")
        fake_ddgs.text.return_value = items

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            results = await provider.search(
                SearchQuery(text="scholarship", country_iso2="JP", locale="ja-JP", gl="jp")
            )

        # a, b, c, dup — the empty-url item and the duplicate are dropped.
        assert len(results) == 4
        assert results[0].url == "https://a.example/x"
        assert results[0].title == "A Scholarship"
        assert results[0].snippet == "fully funded"
        assert results[0].provider_name == "ddgs"
        assert results[0].position == 1
        assert results[1].url == "https://b.example/y"
        assert results[1].snippet == ""
        assert results[2].url == "https://c.example/z"
        assert results[2].title == ""
        # Dedup keeps the first occurrence and its original rank.
        assert results[3].url == "https://dup.example/d"
        assert results[3].position == 5

    @pytest.mark.asyncio
    async def test_prefers_href_then_url_then_embed_url(self):
        provider = DDGSearchProvider(max_results=4)
        items = [
            {"href": "https://href.example/x", "title": "Href wins"},
            {"url": "https://url.example/y", "title": "Url loses to href"},
            {"embed_url": "https://embed.example/w", "title": "Embed wins over nothing"},
            {"link": "https://link.example/v", "title": "Link is last resort"},
        ]

        fake_ddgs = MagicMock(name="FakeDDGS")
        fake_ddgs.text.return_value = items

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            results = await provider.search(SearchQuery(text="q"))

        assert results[0].url == "https://href.example/x"
        assert results[1].url == "https://url.example/y"
        assert results[2].url == "https://embed.example/w"
        assert results[3].url == "https://link.example/v"

    @pytest.mark.asyncio
    async def test_deduplicates_by_url(self):
        provider = DDGSearchProvider(max_results=10)
        items = [
            _item(url="https://same.example/a", title="First"),
            _item(url="https://same.example/a", title="Second"),
            _item(url="https://same.example/a", title="Third"),
            _item(url="https://other.example/b", title="Other"),
        ]

        fake_ddgs = MagicMock(name="FakeDDGS")
        fake_ddgs.text.return_value = items

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            results = await provider.search(SearchQuery(text="q"))

        assert len(results) == 2
        assert results[0].url == "https://same.example/a"
        assert results[1].url == "https://other.example/b"

    @pytest.mark.asyncio
    async def test_no_results_from_upstream_is_an_empty_answer(self):
        """An empty SERP is an answer, not a backend failure.

        The library signals it with DDGSException("No results found.").
        Counting that as a failed query made ordinary long-tail queries look
        like an outage and flipped whole runs to "degraded".
        """
        provider = DDGSearchProvider(max_results=5)

        fake_ddgs = MagicMock(name="FakeDDGS")
        from ddgs.ddgs import DDGSException

        fake_ddgs.text.side_effect = DDGSException("No results found.")

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            results = await provider.search(SearchQuery(text="scholarship japan"))

        assert results == []


class TestDDGSearchProviderEmptyAndMalformed:
    @pytest.mark.asyncio
    async def test_malformed_items_without_url_are_dropped(self):
        provider = DDGSearchProvider(max_results=5)
        items = [
            {"title": "no url at all"},
            {"href": "", "title": "empty url"},
            {"href": "   ", "title": "whitespace url"},
        ]

        fake_ddgs = MagicMock(name="FakeDDGS")
        fake_ddgs.text.return_value = items

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            results = await provider.search(SearchQuery(text="q"))
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_list_from_backend_is_not_a_failure(self):
        provider = DDGSearchProvider(max_results=5)

        fake_ddgs = MagicMock(name="FakeDDGS")
        fake_ddgs.text.return_value = []

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            results = await provider.search(SearchQuery(text="q"))

        assert results == []

    @pytest.mark.asyncio
    async def test_long_body_is_truncated_to_snippet_budget(self):
        provider = DDGSearchProvider(max_results=5)
        long_snippet = "x" * 3000
        items = [_item(snippet=long_snippet)]

        fake_ddgs = MagicMock(name="FakeDDGS")
        fake_ddgs.text.return_value = items

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            results = await provider.search(SearchQuery(text="q"))
        assert results[0].snippet == "x" * 2000

    @pytest.mark.asyncio
    async def test_non_string_values_are_handled_gracefully(self):
        provider = DDGSearchProvider(max_results=5)
        items = [{"href": 123, "title": None, "body": 123}]

        fake_ddgs = MagicMock(name="FakeDDGS")
        fake_ddgs.text.return_value = items

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            results = await provider.search(SearchQuery(text="q"))
        assert results == []


class TestDDGSearchProviderTimeoutsAndErrors:
    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self):
        provider = DDGSearchProvider(timeout=5)

        fake_ddgs = MagicMock(name="FakeDDGS")
        from ddgs.ddgs import TimeoutException

        fake_ddgs.text.side_effect = TimeoutException("timed out")

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            with pytest.raises(TimeoutError, match="timed out"):
                await provider.search(SearchQuery(text="q"))

    @pytest.mark.asyncio
    async def test_ddgs_exception_raises_as_runtime_error(self):
        provider = DDGSearchProvider(timeout=5)

        fake_ddgs = MagicMock(name="FakeDDGS")
        from ddgs.ddgs import DDGSException

        fake_ddgs.text.side_effect = DDGSException("blocked")

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            with pytest.raises(RuntimeError, match="blocked"):
                await provider.search(SearchQuery(text="q"))

    @pytest.mark.asyncio
    async def test_unexpected_exception_raises(self):
        provider = DDGSearchProvider(timeout=5)

        fake_ddgs = MagicMock(name="FakeDDGS")
        fake_ddgs.text.side_effect = RuntimeError("boom")

        with patch.object(_search_mod.ddgs, "_ddgs_client", return_value=fake_ddgs):
            with pytest.raises(RuntimeError, match="boom"):
                await provider.search(SearchQuery(text="q"))


class TestDDGSDoesNotRequireApiKey:
    def test_creation_does_not_read_any_api_key(self, monkeypatch):
        monkeypatch.delenv("POLARIS_SERPER_API_KEY", raising=False)
        monkeypatch.delenv("DDGS_PROXY", raising=False)

        provider = DDGSearchProvider(timeout=7, max_results=8)
        assert provider.name == "ddgs"

    def test_max_results_is_bounded(self):
        provider = DDGSearchProvider(max_results=999)
        assert provider._max_results == 20

    def test_max_results_has_a_floor(self):
        provider = DDGSearchProvider(max_results=0)
        assert provider._max_results == 1


class TestDDGSRegionSelection:
    def test_uses_gl_when_present(self):
        assert DDGSearchProvider._region_for(SearchQuery(text="q", gl="jp")) == "jp-en"

    def test_uses_country_iso2_when_no_gl(self):
        assert DDGSearchProvider._region_for(SearchQuery(text="q", country_iso2="JP")) == "jp-en"

    def test_uses_locale_script(self):
        # ddgs regions are {country}-{lang}; ja-JP means Japanese in Japan.
        assert DDGSearchProvider._region_for(SearchQuery(text="q", locale="ja-JP")) == "jp-ja"

    def test_defaults_to_us_en(self):
        assert DDGSearchProvider._region_for(SearchQuery(text="q")) == "us-en"

    def test_locale_without_country_stays_en(self):
        assert DDGSearchProvider._region_for(SearchQuery(text="q", locale="en")) == "us-en"


class TestFactorySelectsDDGS:
    def test_ddgs_selection(self, monkeypatch):
        monkeypatch.setenv("POLARIS_SEARCH_PROVIDER", "ddgs")
        provider = create_search_provider(timeout=9, max_results=12)
        assert isinstance(provider, DDGSearchProvider)
        assert provider.name == "ddgs"

    def test_ddgs_accepts_max_results(self, monkeypatch):
        monkeypatch.setenv("POLARIS_SEARCH_PROVIDER", "ddgs")
        provider = create_search_provider(timeout=6, max_results=4)
        assert provider._max_results == 4

    def test_invalid_provider_is_rejected(self, monkeypatch):
        monkeypatch.setenv("POLARIS_SEARCH_PROVIDER", "bing_free_magic")
        with pytest.raises(ValueError, match="Unknown POLARIS_SEARCH_PROVIDER"):
            create_search_provider()


class TestExistingProvidersArePreserved:
    def test_null_still_works(self, monkeypatch):
        monkeypatch.setenv("POLARIS_SEARCH_PROVIDER", "null")
        provider = create_search_provider()
        assert provider.name == "null"

    def test_ddgs_default_when_not_set(self, monkeypatch):
        monkeypatch.delenv("POLARIS_SEARCH_PROVIDER", raising=False)
        provider = create_search_provider()
        assert provider.name == "ddgs"
