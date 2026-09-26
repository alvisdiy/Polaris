"""Unit tests for UniversityStrategy."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.ingestion.ecosystem_strategies.university_strategy import UniversityStrategy

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_country():
    """Mock Country for tests."""
    country = MagicMock()
    country.country_id = uuid4()
    country.iso2 = "CN"
    country.iso3 = "CHN"
    country.name = "China"
    return country


@pytest.mark.asyncio
async def test_university_strategy_discover_returns_organizations(mock_country):
    """UniversityStrategy.discover() returns DiscoveredOrganization list."""
    strategy = UniversityStrategy(
        country=mock_country,
        surface_url="https://directory.example.com/universities",
    )

    mock_connector = AsyncMock()
    mock_connector.discover.return_value = [
        "https://pku.edu.cn",
        "https://tsinghua.edu.cn",
    ]

    with patch(
        "services.ingestion.ecosystem_strategies.university_strategy.GenericPlaywrightConnector",
        return_value=mock_connector,
    ):
        result = await strategy.discover()

    assert len(result) == 2
    assert all(org.organization_type == "University" for org in result)
    assert {org.official_url for org in result} == {
        "https://pku.edu.cn",
        "https://tsinghua.edu.cn",
    }
    assert all(org.discovery_method == "link_discovery" for org in result)


@pytest.mark.asyncio
async def test_university_strategy_empty_links(mock_country):
    """UniversityStrategy handles empty link list gracefully."""
    strategy = UniversityStrategy(
        country=mock_country,
        surface_url="https://directory.example.com/universities",
    )

    mock_connector = AsyncMock()
    mock_connector.discover.return_value = []

    with patch(
        "services.ingestion.ecosystem_strategies.university_strategy.GenericPlaywrightConnector",
        return_value=mock_connector,
    ):
        result = await strategy.discover()

    assert result == []


@pytest.mark.asyncio
async def test_university_strategy_connector_closed_on_exit(mock_country):
    """UniversityStrategy closes connector in finally block."""
    strategy = UniversityStrategy(
        country=mock_country,
        surface_url="https://directory.example.com/universities",
    )

    mock_connector = AsyncMock()
    mock_connector.discover.return_value = ["https://example.edu.cn"]

    with patch(
        "services.ingestion.ecosystem_strategies.university_strategy.GenericPlaywrightConnector",
        return_value=mock_connector,
    ):
        await strategy.discover()

    mock_connector.connect.assert_called_once()
    mock_connector.close.assert_called_once()


@pytest.mark.asyncio
async def test_university_strategy_discovered_organizations_have_provenance(mock_country):
    """DiscoveredOrganization objects contain complete provenance."""
    surface_url = "https://directory.example.com/universities"
    strategy = UniversityStrategy(country=mock_country, surface_url=surface_url)

    mock_connector = AsyncMock()
    mock_connector.discover.return_value = ["https://pku.edu.cn"]

    with patch(
        "services.ingestion.ecosystem_strategies.university_strategy.GenericPlaywrightConnector",
        return_value=mock_connector,
    ):
        result = await strategy.discover()

    org = result[0]
    assert org.country_id == mock_country.country_id
    assert org.discovery_source == surface_url
    assert org.discovery_method == "link_discovery"
    assert org.confidence == 0.5
    assert org.evidence == {"origin": "link_discovery"}
    assert org.discovered_at is not None
