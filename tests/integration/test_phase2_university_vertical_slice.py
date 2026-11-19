"""Integration test for Phase 2: University vertical slice end-to-end.

Validates:
1. UniversityStrategy discovers universities
2. CountryEcosystemDiscovery creates Provider rows
3. CountryCoverageOrchestrator wires it into SourceRegistry + scholarship discovery
4. The full CN pipeline works without architectural changes to the downstream flow
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from database.models.country import Country
from database.models.provider import Provider
from database.models.provider_discovery_config import ProviderDiscoveryConfig
from database.models.source_registry import SourceRegistry
from services.ingestion.country_coverage_orchestrator import CountryCoverageOrchestrator

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_phase2_university_discovery_end_to_end(session):
    """Full Phase 2 flow: discover universities → create providers → create sources."""
    # Load or create CN country
    country = session.query(Country).filter_by(iso2="CN").first()
    if not country:
        country = Country(country_id=uuid4(), iso2="CN", iso3="CHN", name="China")
        session.add(country)
        session.commit()

    # Ensure discovery config exists. The assertion below counts providers
    # discovered by *this* surface, so every other active config for the country
    # is switched off first: the seed registry registers real Chinese surfaces,
    # and letting them run against the mocked connector made the count depend on
    # what the seed happened to contain.
    session.query(ProviderDiscoveryConfig).filter(
        ProviderDiscoveryConfig.country_id == country.country_id
    ).update({"is_active": False})
    session.commit()
    config = session.query(ProviderDiscoveryConfig).filter_by(country_id=country.country_id).first()
    if not config:
        config = ProviderDiscoveryConfig(
            config_id=uuid4(),
            country_id=country.country_id,
            discovery_surface_url="https://directory.example.com/universities",
            discovery_strategy="link_discovery",
            allowed_tlds=[".edu.cn", ".ac.cn"],
            keyword_filters=["university", "scholarship"],
            auto_verify_enabled=False,
            confidence_threshold=0.5,
            priority=1,
            is_active=True,
        )
        session.add(config)
        session.commit()
    config.is_active = True
    session.commit()

    # Mock the connector to return test universities
    discovered_urls = [
        "https://pku.edu.cn",
        "https://tsinghua.edu.cn",
        "https://fudan.edu.cn",
    ]

    # Snapshot what already exists for the country. The seed registry also
    # registers universities here, and earlier runs left providers behind, so a
    # test that asserted on "every provider in the country" would be asserting
    # on whatever the database happened to contain.
    before_ids = {
        p.provider_id for p in session.query(Provider).filter_by(country_id=country.country_id)
    }

    mock_connector = AsyncMock()
    mock_connector.discover.return_value = discovered_urls

    with patch(
        "services.ingestion.ecosystem_strategies.link_discovery.GenericPlaywrightConnector",
        return_value=mock_connector,
    ):
        # Run full country coverage with provider discovery enabled
        orchestrator = CountryCoverageOrchestrator("CN", session)
        metrics = await orchestrator.run_full_coverage(
            run_provider_discovery=True,
            run_scholarship_discovery=False,  # Skip scholarship discovery for this test
            max_urls_per_source=50,
        )

    # Assertions: Phase 1 (provider discovery)
    assert metrics.providers_discovered == 3, f"Expected 3 universities discovered, got {metrics.providers_discovered}"

    # Verify providers were created in DB
    providers = session.query(Provider).filter_by(country_id=country.country_id).all()
    assert len(providers) >= 3, f"Expected >= 3 providers in DB, got {len(providers)}"

    # Verify each has correct type and status
    from database.models.enums import ProviderType
    university_providers = [p for p in providers if p.provider_type == ProviderType.UNIVERSITY]
    assert len(university_providers) >= 3, f"Expected >= 3 university providers, got {len(university_providers)}"

    # The providers this run created. The seed registry also registers
    # universities for a country, and those rows are curated by hand — they have
    # no discovery_source by design, so asserting provenance on them would test
    # the seed file, not the discovery flow.
    created_here = [p for p in university_providers if p.provider_id not in before_ids]
    for provider in created_here:
        assert provider.verification_status == "candidate", f"Expected candidate status, got {provider.verification_status}"
        assert provider.discovery_source is not None, "Expected discovery_source to be set"
        assert provider.discovery_method == "link_discovery", "Expected discovery_method to be link_discovery"

    # Every discovered URL must resolve to a provider row, whether this run
    # created it or an earlier one (or the seed registry) already had it.
    provider_urls = {p.official_url for p in university_providers}
    assert provider_urls >= set(discovered_urls), f"Provider URLs {provider_urls} don't match discovered {discovered_urls}"

    # Assertions: Phase 2 (source discovery) - should create SourceRegistry entries
    discovered_provider_ids = [
        p.provider_id for p in university_providers if p.official_url in set(discovered_urls)
    ]
    sources = session.query(SourceRegistry).filter(
        SourceRegistry.provider_id.in_(discovered_provider_ids)
    ).all()
    assert len(sources) >= 3, f"Expected >= 3 SourceRegistry entries, got {len(sources)}"

    for source in sources:
        # Provisional or Active status depending on provider verification
        assert source.status in ["Provisional", "Active"], f"Unexpected source status: {source.status}"
        assert source.official_url is not None, "Expected official_url to be set"

    # Report concrete metrics
    print("\n✓ Phase 2 Vertical Slice Metrics:")
    print(f"  Universities discovered: {metrics.providers_discovered}")
    print(f"  Providers created: {metrics.providers_verified}")
    print(f"  SourceRegistry entries: {len(sources)}")
    print(f"  Errors: {len(metrics.errors)}")
    if metrics.errors:
        for err in metrics.errors:
            print(f"    - {err}")


@pytest.mark.asyncio
async def test_phase2_deduplication_idempotent(session):
    """Running Phase 2 twice should not create duplicate providers."""
    country = session.query(Country).filter_by(iso2="CN").first()
    if not country:
        country = Country(country_id=uuid4(), iso2="CN", iso3="CHN", name="China")
        session.add(country)
        session.commit()

    config = session.query(ProviderDiscoveryConfig).filter_by(country_id=country.country_id).first()
    if not config:
        config = ProviderDiscoveryConfig(
            config_id=uuid4(),
            country_id=country.country_id,
            discovery_surface_url="https://directory.example.com/universities",
            discovery_strategy="link_discovery",
            allowed_tlds=[".edu.cn"],
            keyword_filters=[],
            auto_verify_enabled=False,
            confidence_threshold=0.5,
            priority=1,
            is_active=True,
        )
        session.add(config)
        session.commit()

    discovered_urls = ["https://pku.edu.cn", "https://tsinghua.edu.cn"]
    mock_connector = AsyncMock()
    mock_connector.discover.return_value = discovered_urls

    with patch(
        "services.ingestion.ecosystem_strategies.link_discovery.GenericPlaywrightConnector",
        return_value=mock_connector,
    ):
        orchestrator = CountryCoverageOrchestrator("CN", session)

        # Run 1
        metrics1 = await orchestrator.run_full_coverage(
            run_provider_discovery=True,
            run_scholarship_discovery=False,
        )
        from database.models.enums import ProviderType
        providers_after_run1 = len(
            session.query(Provider)
            .filter_by(country_id=country.country_id, provider_type=ProviderType.UNIVERSITY)
            .all()
        )

        # Run 2 (same config, same URLs)
        metrics2 = await orchestrator.run_full_coverage(
            run_provider_discovery=True,
            run_scholarship_discovery=False,
        )
        from database.models.enums import ProviderType
        providers_after_run2 = len(
            session.query(Provider)
            .filter_by(country_id=country.country_id, provider_type=ProviderType.UNIVERSITY)
            .all()
        )

    # Idempotency: same number of providers after second run
    assert (
        providers_after_run1 == providers_after_run2
    ), f"Idempotency failed: {providers_after_run1} vs {providers_after_run2}"

    print("\n✓ Idempotency Test Passed:")
    print(f"  Run 1: {metrics1.providers_discovered} discovered → {providers_after_run1} providers in DB")
    print(f"  Run 2: {metrics2.providers_discovered} discovered → {providers_after_run2} providers in DB")
