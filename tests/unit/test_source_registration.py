"""Unit tests for source registration service."""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from services.discovery.source_registration import (
    _normalize_domain,
    _get_or_create_provider,
    register_source,
)


@pytest.mark.unit
class TestNormalizeDomain:
    """Test domain normalization for provider_code."""

    def test_normalize_full_url(self):
        """Normalize full HTTPS URL to provider_code."""
        result = _normalize_domain("https://www.studyinjapan.go.jp/en/")
        assert result == "studyinjapan-go-jp"

    def test_normalize_domain_only(self):
        """Normalize domain without protocol."""
        result = _normalize_domain("daad.de")
        assert result == "daad-de"

    def test_normalize_removes_www(self):
        """Remove www. prefix."""
        result = _normalize_domain("www.example.com")
        assert result == "example-com"

    def test_normalize_handles_path(self):
        """Handle URLs with paths."""
        result = _normalize_domain("https://example.com/path/to/page")
        assert result == "example-com"

    def test_normalize_lowercase(self):
        """Ensure result is lowercase."""
        result = _normalize_domain("HTTPS://WWW.EXAMPLE.COM")
        assert result == "example-com"


@pytest.mark.unit
class TestGetOrCreateProvider:
    """Test provider creation and retrieval."""

    def test_creates_new_provider(self):
        """Create new provider when not exists."""
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        country_id = uuid4()
        provider = _get_or_create_provider(
            provider_code="test-provider",
            provider_name="Test Provider",
            provider_type="GOVERNMENT",
            country_id=country_id,
            session=session,
        )

        assert provider.provider_code == "test-provider"
        assert provider.provider_name == "Test Provider"
        assert provider.verification_status == "unverified"
        session.add.assert_called_once()

    def test_returns_existing_provider(self):
        """Return existing provider when provider_code matches."""
        existing = MagicMock(provider_code="existing-provider")
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = existing

        country_id = uuid4()
        provider = _get_or_create_provider(
            provider_code="existing-provider",
            provider_name="New Name",
            provider_type="GOVERNMENT",
            country_id=country_id,
            session=session,
        )

        assert provider == existing
        session.add.assert_not_called()


@pytest.mark.unit
class TestRegisterSource:
    """Test complete source registration."""

    @patch("services.discovery.source_registration._get_or_create_provider")
    def test_register_source_success(self, mock_get_or_create):
        """Successfully register a new source."""
        # Setup mocks
        country = MagicMock(country_id=uuid4(), iso2="JP")
        provider = MagicMock(provider_id=uuid4(), provider_name="MEXT")

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = country
        mock_get_or_create.return_value = provider

        # Execute
        result_provider, result_source = register_source(
            country_iso2="JP",
            official_url="https://www.studyinjapan.go.jp/en/",
            provider_name="MEXT",
            provider_type="GOVERNMENT",
            session=session,
        )

        # Verify
        assert result_provider == provider
        assert result_source.country_id == country.country_id
        assert result_source.provider_id == provider.provider_id
        session.commit.assert_called_once()

    def test_register_source_country_not_found(self):
        """Raise error when country not found."""
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(ValueError, match="Country not found"):
            register_source(
                country_iso2="XX",
                official_url="https://example.com",
                provider_name="Test",
                provider_type="GOVERNMENT",
                session=session,
            )
