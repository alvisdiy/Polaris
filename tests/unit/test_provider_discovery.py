"""Unit tests for Provider Discovery Orchestrator."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database.models.country import Country
from database.models.enums import ProviderType
from database.models.provider import Provider
from database.models.provider_discovery_config import ProviderDiscoveryConfig
from services.ingestion.provider_discovery import (
    ProviderDiscoveryMetrics,
    ProviderDiscoveryOrchestrator,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_session():
    """Mock database session."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    session.flush = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    return session


@pytest.fixture
def sample_country():
    """Sample country fixture."""
    return Country(
        country_id=uuid.uuid4(),
        iso2="JP",
        iso3="JPN",
        name="Japan",
    )


@pytest.fixture
def sample_config(sample_country):
    """Sample discovery config fixture."""
    return ProviderDiscoveryConfig(
        config_id=uuid.uuid4(),
        country_id=sample_country.country_id,
        discovery_surface_url="https://www.jasso.go.jp/en/",
        discovery_strategy="link_discovery",
        allowed_tlds=[".go.jp", ".ac.jp"],
        keyword_filters=["scholarship", "grant"],
        auto_verify_enabled=True,
        confidence_threshold=0.75,
        priority=1,
        is_active=True,
    )


def test_infer_provider_type_government():
    """Test provider type inference for government domains."""
    orchestrator = ProviderDiscoveryOrchestrator(MagicMock())

    p_type, confidence = orchestrator._infer_provider_type("jasso.go.jp", ".go.jp")
    assert p_type == ProviderType.GOVERNMENT
    assert confidence == 0.9


def test_infer_provider_type_university():
    """Test provider type inference for university domains."""
    orchestrator = ProviderDiscoveryOrchestrator(MagicMock())

    p_type, confidence = orchestrator._infer_provider_type("tokyo.ac.jp", ".ac.jp")
    assert p_type == ProviderType.UNIVERSITY
    assert confidence == 0.9


def test_infer_provider_type_foundation():
    """Test provider type inference for foundation domains."""
    orchestrator = ProviderDiscoveryOrchestrator(MagicMock())

    p_type, confidence = orchestrator._infer_provider_type("toyota-foundation.or.jp", ".or.jp")
    assert p_type == ProviderType.FOUNDATION
    assert confidence == 0.8


def test_infer_provider_type_fallback():
    """Test provider type inference fallback for unknown domains."""
    orchestrator = ProviderDiscoveryOrchestrator(MagicMock())

    p_type, confidence = orchestrator._infer_provider_type("unknown-org.com", ".com")
    assert p_type == ProviderType.NGO
    assert confidence == 0.3


@pytest.mark.asyncio
async def test_discover_providers_no_country(mock_session):
    """Test discovery when country not found."""
    mock_session.query.return_value.filter_by.return_value.first.return_value = None

    orchestrator = ProviderDiscoveryOrchestrator(mock_session)
    metrics = await orchestrator.discover_providers_for_country("XX")

    assert metrics.country_iso2 == "XX"
    assert len(metrics.errors) > 0
    assert "not found" in metrics.errors[0]


@pytest.mark.asyncio
async def test_discover_providers_no_configs(mock_session, sample_country):
    """Test discovery when no configs exist for country."""
    mock_session.query.return_value.filter_by.return_value.first.return_value = sample_country
    mock_session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

    orchestrator = ProviderDiscoveryOrchestrator(mock_session)
    metrics = await orchestrator.discover_providers_for_country("JP")

    assert metrics.country_iso2 == "JP"
    assert metrics.discovery_surfaces_processed == 0


@pytest.mark.asyncio
async def test_process_config_unknown_strategy(mock_session, sample_country, sample_config):
    """Test processing config with unknown discovery strategy."""
    sample_config.discovery_strategy = "unknown_strategy"

    orchestrator = ProviderDiscoveryOrchestrator(mock_session)
    orchestrator.metrics = ProviderDiscoveryMetrics(country_iso2="JP")

    await orchestrator._process_config(sample_country, sample_config)

    assert orchestrator.metrics.discovery_surfaces_processed == 1
    assert len(orchestrator.metrics.errors) > 0
    assert "not implemented" in orchestrator.metrics.errors[0]


@pytest.mark.asyncio
async def test_evaluate_candidate_creates_new_provider(mock_session, sample_country, sample_config):
    """Test candidate evaluation creates a new provider."""
    # Mock no existing provider
    mock_session.query.return_value.filter.return_value.first.return_value = None

    link_data = {
        'full_url': 'https://jasso.go.jp/en/scholarship/',
        'parsed': MagicMock(netloc='jasso.go.jp', path='/en/scholarship/', query=''),
        'text': 'JASSO Scholarships',
        'title': '',
        'matched_tld': '.go.jp',
        'matched_keywords': ['scholarship'],
    }

    orchestrator = ProviderDiscoveryOrchestrator(mock_session)
    orchestrator.metrics = ProviderDiscoveryMetrics(country_iso2="JP")

    await orchestrator._evaluate_candidate(sample_country, sample_config, link_data)

    assert orchestrator.metrics.providers_created == 1
    assert orchestrator.metrics.verification_passed == 1
    mock_session.add.assert_called()
    mock_session.flush.assert_called()


@pytest.mark.asyncio
async def test_evaluate_candidate_duplicate_provider(mock_session, sample_country, sample_config):
    """Test candidate evaluation with existing provider."""
    existing_provider = Provider(
        provider_id=uuid.uuid4(),
        provider_code="JASSO_GO_JP",
        provider_name="JASSO",
        provider_type=ProviderType.GOVERNMENT,
        country_id=sample_country.country_id,
        official_url="https://jasso.go.jp/en/scholarship/",
        verification_status="verified",
    )
    existing_provider.is_verified = MagicMock(return_value=True)

    mock_session.query.return_value.filter.return_value.first.return_value = existing_provider

    link_data = {
        'full_url': 'https://jasso.go.jp/en/scholarship/',
        'parsed': MagicMock(netloc='jasso.go.jp', path='/en/scholarship/', query=''),
        'text': 'JASSO Scholarships',
        'title': '',
        'matched_tld': '.go.jp',
        'matched_keywords': ['scholarship'],
    }

    orchestrator = ProviderDiscoveryOrchestrator(mock_session)
    orchestrator.metrics = ProviderDiscoveryMetrics(country_iso2="JP")

    await orchestrator._evaluate_candidate(sample_country, sample_config, link_data)

    assert orchestrator.metrics.duplicates_skipped == 1
    assert orchestrator.metrics.providers_updated == 1


@pytest.mark.asyncio
async def test_evaluate_candidate_low_confidence_requires_review(mock_session, sample_country, sample_config):
    """Test candidate with low confidence requires human review."""
    mock_session.query.return_value.filter.return_value.first.return_value = None

    link_data = {
        'full_url': 'https://example.com/scholarship/',
        'parsed': MagicMock(netloc='example.com', path='/scholarship/', query=''),
        'text': 'Some Scholarship',
        'title': '',
        'matched_tld': 'any',
        'matched_keywords': ['scholarship'],
    }

    orchestrator = ProviderDiscoveryOrchestrator(mock_session)
    orchestrator.metrics = ProviderDiscoveryMetrics(country_iso2="JP")

    await orchestrator._evaluate_candidate(sample_country, sample_config, link_data)

    # Low confidence (0.3) means candidate status, not auto-verified
    assert orchestrator.metrics.verification_pending_review == 1
    assert orchestrator.metrics.verification_passed == 0


def test_metrics_to_dict():
    """Test metrics serialization."""
    metrics = ProviderDiscoveryMetrics(country_iso2="JP")
    metrics.providers_created = 5
    metrics.verification_passed = 3
    metrics.errors.append("test error")

    result = metrics.to_dict()

    assert result["country_iso2"] == "JP"
    assert result["providers_created"] == 5
    assert result["verification_passed"] == 3
    assert "test error" in result["errors"]
    assert "started_at" in result
