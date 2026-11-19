"""Unit tests for CountryEcosystemDiscovery orchestrator.

These tests use mocked sessions to avoid depending on the real database.
They verify orchestration, deduplication, persistence calls, and metrics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from database.models.provider import Provider
from services.ingestion.ecosystem_discovery import (
    CountryEcosystemDiscovery,
    EcosystemDiscoveryMetrics,
    _normalize_url,
    _provider_code_from_url,
)
from services.ingestion.ecosystem_strategies import (
    DiscoveredOrganization,
    OrganizationDiscoveryStrategy,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_country():
    """Mock Country object for unit tests."""
    country = MagicMock()
    country.country_id = uuid4()
    country.iso2 = "CN"
    country.iso3 = "CHN"
    country.name = "China"
    return country


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy session for unit tests."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    return session


class MockStrategy(OrganizationDiscoveryStrategy):
    """Mock strategy that returns predefined organizations."""

    def __init__(self, country, orgs_to_return):
        super().__init__(country)
        self.orgs_to_return = orgs_to_return

    async def discover(self):
        return self.orgs_to_return


class FailingStrategy(OrganizationDiscoveryStrategy):
    """Mock strategy that always raises an exception."""

    async def discover(self):
        raise RuntimeError("Mock strategy failure")


def test_normalize_url_strips_www_and_lowercases():
    assert _normalize_url("https://WWW.example.com/path") == "https://example.com/path"
    assert _normalize_url("http://example.com") == "http://example.com/"
    assert _normalize_url("https://sub.example.com/") == "https://sub.example.com/"


def test_provider_code_uses_registered_domain():
    # Identity is the organisation (domain), not the path.
    code = _provider_code_from_url("https://www.example.com/admissions")
    assert code == "EXAMPLE_COM"


def test_provider_code_stable_for_same_url():
    url = "https://example.edu.cn/scholarships"
    code1 = _provider_code_from_url(url)
    code2 = _provider_code_from_url(url)
    assert code1 == code2


def test_provider_code_is_the_same_for_two_pages_of_one_domain():
    code1 = _provider_code_from_url("https://example.com")
    code2 = _provider_code_from_url("https://example.com/different")
    assert code1 == code2 == "EXAMPLE_COM"


@pytest.mark.asyncio
async def test_discover_with_no_strategies(mock_session, mock_country):
    """When no strategies are provided, metrics show zero."""
    engine = CountryEcosystemDiscovery(mock_session)
    metrics = await engine.discover(mock_country, strategies=[])

    assert metrics.strategies_executed == 0
    assert metrics.organizations_discovered == 0
    assert metrics.organizations_created == 0
    assert metrics.country_iso2 == "CN"


@pytest.mark.asyncio
async def test_discover_creates_new_providers(mock_session, mock_country):
    """New organizations discovered by strategies result in Provider add calls."""
    org1 = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Peking University",
        organization_type="University",
        official_url="https://pku.edu.cn",
        discovery_source="http://directory.cn",
        discovery_method="link_discovery",
        confidence=0.8,
    )
    org2 = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Tsinghua University",
        organization_type="University",
        official_url="https://tsinghua.edu.cn",
        discovery_source="http://directory.cn",
        discovery_method="link_discovery",
        confidence=0.8,
    )

    strategy = MockStrategy(mock_country, [org1, org2])
    engine = CountryEcosystemDiscovery(mock_session)
    metrics = await engine.discover(mock_country, [strategy])

    assert metrics.strategies_executed == 1
    assert metrics.organizations_discovered == 2
    assert metrics.organizations_created == 2
    assert metrics.organizations_updated == 0
    assert metrics.duplicates_skipped == 0

    # Should have added 2 Provider instances and committed.
    assert mock_session.add.call_count == 2
    added_providers = [call.args[0] for call in mock_session.add.call_args_list]
    assert all(isinstance(p, Provider) for p in added_providers)
    assert {p.provider_name for p in added_providers} == {"Peking University", "Tsinghua University"}
    assert all(p.verification_status == "candidate" for p in added_providers)
    mock_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_discover_deduplicates_within_run(mock_session, mock_country):
    """Duplicate URLs within a single run are detected and skipped."""
    org1 = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Peking University",
        organization_type="University",
        official_url="https://pku.edu.cn",
        discovery_source="http://directory.cn",
        discovery_method="link_discovery",
    )
    org2 = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Peking University (www)",
        organization_type="University",
        official_url="https://www.pku.edu.cn",  # www variant - normalizes to same
        discovery_source="http://directory.cn",
        discovery_method="link_discovery",
    )

    strategy = MockStrategy(mock_country, [org1, org2])
    engine = CountryEcosystemDiscovery(mock_session)
    metrics = await engine.discover(mock_country, [strategy])

    assert metrics.organizations_discovered == 2
    assert metrics.organizations_created == 1
    assert metrics.duplicates_skipped == 1
    assert mock_session.add.call_count == 1


@pytest.mark.asyncio
async def test_discover_updates_existing_provider(mock_session, mock_country):
    """Existing providers are updated if missing discovery provenance."""
    existing = Provider(
        provider_code=_provider_code_from_url("https://pku.edu.cn"),
        provider_name="Peking University",
        provider_type="University",
        country_id=mock_country.country_id,
        official_url="https://pku.edu.cn",
        verification_status="verified",  # Already verified
        discovery_source=None,  # Missing provenance
    )
    mock_session.query.return_value.filter.return_value.first.return_value = existing

    org = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Peking University",
        organization_type="University",
        official_url="https://pku.edu.cn",
        discovery_source="http://directory.cn",
        discovery_method="link_discovery",
    )

    strategy = MockStrategy(mock_country, [org])
    engine = CountryEcosystemDiscovery(mock_session)
    metrics = await engine.discover(mock_country, [strategy])

    assert metrics.organizations_created == 0
    assert metrics.organizations_updated == 1
    assert existing.discovery_source == "http://directory.cn"
    assert existing.verification_status == "verified"  # Status preserved
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_discover_does_not_downgrade_verified_provider(mock_session, mock_country):
    """A re-discovered verified provider must remain verified."""
    existing = Provider(
        provider_code=_provider_code_from_url("https://pku.edu.cn"),
        provider_name="Peking University",
        provider_type="University",
        country_id=mock_country.country_id,
        official_url="https://pku.edu.cn",
        verification_status="verified",
        discovery_source="http://old-source.cn",  # Already has provenance
    )
    mock_session.query.return_value.filter.return_value.first.return_value = existing

    org = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Peking University",
        organization_type="University",
        official_url="https://pku.edu.cn",
        discovery_source="http://new-source.cn",
        discovery_method="link_discovery",
    )

    strategy = MockStrategy(mock_country, [org])
    engine = CountryEcosystemDiscovery(mock_session)
    metrics = await engine.discover(mock_country, [strategy])

    assert metrics.organizations_created == 0
    assert metrics.organizations_updated == 1
    # Provenance already present; should not be overwritten.
    assert existing.discovery_source == "http://old-source.cn"
    assert existing.verification_status == "verified"


@pytest.mark.asyncio
async def test_discover_handles_strategy_failure_gracefully(mock_session, mock_country):
    """If one strategy fails, others continue and error is recorded."""
    org = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Peking University",
        organization_type="University",
        official_url="https://pku.edu.cn",
        discovery_source="http://directory.cn",
        discovery_method="link_discovery",
    )

    good_strategy = MockStrategy(mock_country, [org])
    bad_strategy = FailingStrategy(mock_country)

    engine = CountryEcosystemDiscovery(mock_session)
    metrics = await engine.discover(mock_country, [bad_strategy, good_strategy])

    assert metrics.strategies_executed == 1  # Only good one succeeded
    assert metrics.organizations_created == 1
    assert len(metrics.errors) == 1
    assert "FailingStrategy" in metrics.errors[0]


@pytest.mark.asyncio
async def test_discover_multiple_strategies(mock_session, mock_country):
    """Multiple strategies' results are aggregated."""
    org1 = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Peking University",
        organization_type="University",
        official_url="https://pku.edu.cn",
        discovery_source="http://directory.cn",
        discovery_method="link_discovery",
    )
    org2 = DiscoveredOrganization(
        country_id=mock_country.country_id,
        name="Ministry of Education",
        organization_type="Government",
        official_url="https://moe.gov.cn",
        discovery_source="http://gov.cn",
        discovery_method="government_portal",
    )

    strategy1 = MockStrategy(mock_country, [org1])
    strategy2 = MockStrategy(mock_country, [org2])

    engine = CountryEcosystemDiscovery(mock_session)
    metrics = await engine.discover(mock_country, [strategy1, strategy2])

    assert metrics.strategies_executed == 2
    assert metrics.organizations_discovered == 2
    assert metrics.organizations_created == 2

    added_providers = [call.args[0] for call in mock_session.add.call_args_list]
    assert {p.provider_type.value for p in added_providers} == {"University", "Government"}


def test_metrics_to_dict():
    """Metrics serialize correctly to dict."""
    metrics = EcosystemDiscoveryMetrics(
        country_iso2="CN",
        started_at=datetime(2026, 9, 20, 3, 0, 0, tzinfo=timezone.utc),
    )
    metrics.finished_at = datetime(2026, 9, 20, 3, 5, 0, tzinfo=timezone.utc)
    metrics.organizations_created = 10

    data = metrics.to_dict()
    assert data["country_iso2"] == "CN"
    assert data["organizations_created"] == 10
    assert "started_at" in data
    assert "finished_at" in data
