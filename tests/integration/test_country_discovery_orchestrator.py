"""CountryDiscoveryOrchestrator (services/ingestion/country_orchestrator.py).

The legacy country-level driver sat at 38% coverage: source selection
(active/provisional, this country only), the entry-URL and blocked-host
refusals, connector dispatch (named vs Playwright-by-crawl-method),
per-source failure isolation and metric aggregation were unmeasured.
These tests seed real registry rows and replace the connector map and
the per-source orchestrator at the module's seams.
"""

from __future__ import annotations

import uuid

import pytest

import services.ingestion.country_orchestrator as country_module
from database.models.country import Country
from database.models.source_registry import SourceRegistry
from services.ingestion.country_orchestrator import CountryDiscoveryOrchestrator
from services.ingestion.discovery import DiscoveryMetrics

pytestmark = pytest.mark.integration


class FakeConnector:
    instances: list = []

    def __init__(self, config):
        self.config = config
        FakeConnector.instances.append(self)
        self.closed = False

    async def connect(self):
        return None

    async def close(self):
        self.closed = True


class FakeDiscoveryOrchestrator:
    """Returns canned metrics, or raises for sources marked to explode."""

    def __init__(self, connector, session):
        self.connector = connector

    async def discover_and_process(self, max_urls=50):
        if "explode" in str(self.connector.config.url):
            raise RuntimeError("connector blew up")
        return DiscoveryMetrics(
            source_id=self.connector.config.source_id,
            candidate_urls_found=3,
            fetch_succeeded=2,
            persisted=1,
            duplicates_skipped=1,
            errors=["one bad page"],
        )


@pytest.fixture(autouse=True)
def _seams(monkeypatch):
    FakeConnector.instances = []
    monkeypatch.setattr(country_module, "DiscoveryOrchestrator", FakeDiscoveryOrchestrator)
    monkeypatch.setitem(
        country_module._CONNECTOR_MAP,
        "fake_connector",
        FakeConnector,
    )
    monkeypatch.setitem(
        country_module._CONNECTOR_MAP,
        "generic_playwright",
        FakeConnector,
    )


def _country(session, iso2):
    country = session.query(Country).filter(Country.iso2 == iso2).first()
    if country is None:
        country = Country(iso2=iso2, iso3=f"{iso2}X", name=f"Testland {iso2}")
        session.add(country)
        session.flush()
    return country


def _source(session, country, name, **overrides):
    suffix = uuid.uuid4().hex[:8]
    fields = dict(
        source_name=f"{name} {suffix}",
        country_id=country.country_id,
        official_url=f"https://example.org/{suffix}/",
        crawl_entry_url=f"https://example.org/{suffix}/en/",
        crawl_method="HTTP",
        crawl_frequency="monthly",
        status="Active",
        verification_state="VERIFIED",
        connector_name="fake_connector",
    )
    fields.update(overrides)
    source = SourceRegistry(**fields)
    session.add(source)
    session.flush()
    return source


class TestDiscoverAllSources:
    @pytest.mark.asyncio
    async def test_aggregation_and_source_selection(self, exploration_session):
        session = exploration_session
        jp = _country(session, "JP")
        good = _source(session, jp, "Good Source")
        _source(session, jp, "Paused Source", status="Paused")
        de = _country(session, "DE")
        _source(session, de, "Other Country Source")

        orch = CountryDiscoveryOrchestrator("JP", session)
        report = await orch.discover_all_sources()

        assert report.total_sources == 1
        assert report.sources_processed == 1
        assert report.total_candidates == 3
        assert report.total_fetched == 2
        assert report.total_persisted == 1
        assert report.total_duplicates == 1
        assert report.total_errors == 1
        assert good.source_name in report.per_source_metrics
        assert report.finished_at is not None
        as_dict = report.to_dict()
        assert as_dict["country_iso2"] == "JP"
        assert as_dict["per_source_metrics"][good.source_name]["persisted"] == 1
        # The connector was closed even on the happy path.
        assert FakeConnector.instances and FakeConnector.instances[0].closed is True

    @pytest.mark.asyncio
    async def test_no_sources_finalizes_empty(self, exploration_session):
        orch = CountryDiscoveryOrchestrator("JP", exploration_session)
        report = await orch.discover_all_sources()
        assert report.total_sources == 0
        assert report.sources_processed == 0
        assert report.finished_at is not None

    @pytest.mark.asyncio
    async def test_a_failing_source_does_not_stop_the_country(self, exploration_session):
        session = exploration_session
        jp = _country(session, "JP")
        _source(
            session,
            jp,
            "Exploding Source",
            crawl_entry_url="https://example.org/explode/",
            official_url="https://example.org/explode/",
        )
        good = _source(session, jp, "Good Source")

        orch = CountryDiscoveryOrchestrator("JP", session)
        report = await orch.discover_all_sources()
        assert report.sources_processed == 1
        assert good.source_name in report.per_source_metrics
        assert any("Exploding Source" in e for e in report.errors)


class TestProcessSourceGuards:
    @pytest.mark.asyncio
    async def test_missing_entry_url_is_an_error_not_a_crash(self, exploration_session):
        # The registry columns are NOT NULL, so a persisted row cannot
        # reach this guard; a transient row pins the guard's behaviour
        # for callers that build sources in memory.
        source = SourceRegistry(
            source_name="Urlless",
            country_id=uuid.uuid4(),
            official_url=None,
            crawl_entry_url=None,
            crawl_method="HTTP",
            crawl_frequency="monthly",
            status="Active",
            verification_state="VERIFIED",
            connector_name="fake_connector",
        )
        orch = CountryDiscoveryOrchestrator("JP", exploration_session)
        await orch._process_source(source, 10)
        assert any("no crawl_entry_url" in e for e in orch.report.errors)
        assert orch.report.sources_processed == 0

    @pytest.mark.asyncio
    async def test_a_blocked_aggregator_host_is_refused(self, exploration_session):
        session = exploration_session
        jp = _country(session, "JP")
        source = _source(
            session,
            jp,
            "Social Mirror",
            crawl_entry_url="https://facebook.com/somepage",
            official_url="https://facebook.com/somepage",
        )
        orch = CountryDiscoveryOrchestrator("JP", session)
        await orch._process_source(source, 10)
        assert any("not an official source" in e for e in orch.report.errors)
        assert FakeConnector.instances == []

    @pytest.mark.asyncio
    async def test_an_unknown_connector_is_reported(self, exploration_session):
        session = exploration_session
        jp = _country(session, "JP")
        source = _source(session, jp, "Mystery", connector_name="does_not_exist")
        orch = CountryDiscoveryOrchestrator("JP", session)
        await orch._process_source(source, 10)
        assert any("unknown connector" in e for e in orch.report.errors)

    @pytest.mark.asyncio
    async def test_playwright_crawl_method_selects_the_playwright_connector(
        self, exploration_session
    ):
        session = exploration_session
        jp = _country(session, "JP")
        source = _source(
            session, jp, "Rendered", crawl_method="Playwright", connector_name=None
        )
        orch = CountryDiscoveryOrchestrator("JP", session)
        await orch._process_source(source, 10)
        assert orch.report.sources_processed == 1
        assert len(FakeConnector.instances) == 1
