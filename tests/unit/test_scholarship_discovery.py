"""Unit tests for scholarship discovery orchestrator."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import uuid4

from services.discovery.scholarship_discovery import (
    _instantiate_connector,
    _normalize_url,
    discover_scholarships_for_country,
    discover_scholarships_for_source,
)


@pytest.mark.unit
class TestInstantiateConnector:
    """Test dynamic connector instantiation."""

    def test_instantiate_mext_connector(self):
        """Instantiate MEXTConnector by name."""
        from services.ingestion.connectors.base_connector import ConnectorConfig

        config = ConnectorConfig(
            source_id=uuid4(),
            url="https://www.studyinjapan.go.jp/en/",
        )

        connector = _instantiate_connector("mext_connector", config)
        assert connector is not None
        assert hasattr(connector, "discover")

    def test_instantiate_generic_http(self):
        """Instantiate GenericHTTPConnector by name."""
        from services.ingestion.connectors.base_connector import ConnectorConfig

        config = ConnectorConfig(
            source_id=uuid4(),
            url="https://example.com",
        )

        connector = _instantiate_connector("generic_http", config)
        assert connector is not None
        assert hasattr(connector, "discover")

    def test_instantiate_unknown_connector(self):
        """Raise error for unknown connector."""
        from services.ingestion.connectors.base_connector import ConnectorConfig

        config = ConnectorConfig(source_id=uuid4(), url="https://example.com")

        with pytest.raises(ValueError, match="Unknown connector"):
            _instantiate_connector("unknown_connector", config)


@pytest.mark.unit
class TestNormalizeUrl:
    """Test URL normalization for deduplication."""

    def test_removes_fragment(self):
        """Remove URL fragment."""
        result = _normalize_url("https://example.com/page#section")
        assert result == "https://example.com/page"

    def test_removes_trailing_slash(self):
        """Remove trailing slash."""
        result = _normalize_url("https://example.com/page/")
        assert result == "https://example.com/page"

    def test_combined_normalization(self):
        """Remove both fragment and trailing slash."""
        result = _normalize_url("https://example.com/page/#section")
        assert result == "https://example.com/page"


@pytest.mark.unit
class TestDiscoverScholarshipsForCountry:
    """Test country-level scholarship discovery."""

    def test_country_not_found(self):
        """Raise error when country not found."""
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="Country not found"):
            discover_scholarships_for_country("XX", session)

    def test_no_sources_for_country(self):
        """Return empty list when no sources registered."""
        country = MagicMock(country_id=uuid4())
        session = MagicMock()

        # First call returns country, second returns empty sources list
        session.query.return_value.filter.return_value.first.return_value = country
        session.query.return_value.filter.return_value.all.return_value = []

        result = discover_scholarships_for_country("JP", session)
        assert result == []

    @patch("services.discovery.scholarship_discovery.asyncio.run")
    def test_discovers_from_multiple_sources(self, mock_asyncio_run):
        """Aggregate URLs from multiple sources."""
        country = MagicMock(country_id=uuid4())
        provider = MagicMock(provider_name="Test Provider")

        source1 = MagicMock(
            source_id=uuid4(),
            source_name="Source 1",
            crawl_entry_url="https://source1.com",
            connector_name="generic_http",
            provider=provider,
        )
        source2 = MagicMock(
            source_id=uuid4(),
            source_name="Source 2",
            crawl_entry_url="https://source2.com",
            connector_name="generic_http",
            provider=provider,
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = country
        session.query.return_value.filter.return_value.all.return_value = [source1, source2]

        # Mock async discovery results
        mock_asyncio_run.return_value = [
            [
                {
                    "url": "https://source1.com/scholarship1",
                    "source_id": str(source1.source_id),
                    "source_name": "Source 1",
                    "provider_name": "Test Provider",
                    "connector_name": "generic_http",
                }
            ],
            [
                {
                    "url": "https://source2.com/scholarship2",
                    "source_id": str(source2.source_id),
                    "source_name": "Source 2",
                    "provider_name": "Test Provider",
                    "connector_name": "generic_http",
                }
            ],
        ]

        result = discover_scholarships_for_country("JP", session)

        assert len(result) == 2
        assert result[0]["url"] == "https://source1.com/scholarship1"
        assert result[1]["url"] == "https://source2.com/scholarship2"

    @patch("services.discovery.scholarship_discovery.asyncio.run")
    def test_deduplicates_urls(self, mock_asyncio_run):
        """Deduplicate identical URLs from different sources."""
        country = MagicMock(country_id=uuid4())
        provider = MagicMock(provider_name="Test Provider")

        source = MagicMock(
            source_id=uuid4(),
            source_name="Source",
            crawl_entry_url="https://source.com",
            connector_name="generic_http",
            provider=provider,
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = country
        session.query.return_value.filter.return_value.all.return_value = [source]

        # Same URL discovered twice (with/without trailing slash)
        mock_asyncio_run.return_value = [
            [
                {
                    "url": "https://source.com/scholarship/",
                    "source_id": str(source.source_id),
                    "source_name": "Source",
                    "provider_name": "Test Provider",
                    "connector_name": "generic_http",
                },
                {
                    "url": "https://source.com/scholarship",  # Duplicate
                    "source_id": str(source.source_id),
                    "source_name": "Source",
                    "provider_name": "Test Provider",
                    "connector_name": "generic_http",
                },
            ]
        ]

        result = discover_scholarships_for_country("JP", session)

        # Should deduplicate to 1
        assert len(result) == 1


@pytest.mark.unit
class TestDiscoverScholarshipsForSource:
    """Test single-source scholarship discovery."""

    def test_source_not_found(self):
        """Raise error when source not found."""
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="Source not found"):
            discover_scholarships_for_source(uuid4(), session)

    @patch("services.discovery.scholarship_discovery.asyncio.run")
    def test_discovers_from_source(self, mock_asyncio_run):
        """Discover scholarships from a single source."""
        source_id = uuid4()
        provider = MagicMock(provider_name="Test Provider")

        source = MagicMock(
            source_id=source_id,
            source_name="Test Source",
            crawl_entry_url="https://test.com",
            connector_name="generic_http",
            provider=provider,
        )

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = source

        mock_asyncio_run.return_value = [
            {
                "url": "https://test.com/scholarship1",
                "source_id": str(source_id),
                "source_name": "Test Source",
                "provider_name": "Test Provider",
                "connector_name": "generic_http",
            }
        ]

        result = discover_scholarships_for_source(source_id, session)

        assert len(result) == 1
        assert result[0]["url"] == "https://test.com/scholarship1"
