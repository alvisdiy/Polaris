"""Run CN University Discovery vertical slice.

Phase 2: Prove the CountryEcosystemDiscovery engine works end-to-end for CN.
"""

import asyncio

from database.models.country import Country
from database.models.provider_discovery_config import ProviderDiscoveryConfig
from database.session import SessionLocal
from services.ingestion.ecosystem_discovery import CountryEcosystemDiscovery
from services.ingestion.ecosystem_strategies.university_strategy import UniversityStrategy


async def main():
    session = SessionLocal()

    try:
        # Load CN country record
        country = session.query(Country).filter_by(iso2="CN").first()
        if not country:
            print("[FAIL] Country CN not found in database")
            return

        print(f"[OK] Loaded country: {country.name} ({country.iso2})")

        # Load CN university discovery config
        config = (
            session.query(ProviderDiscoveryConfig)
            .filter_by(country_id=country.country_id, is_active=True)
            .first()
        )
        if not config:
            print("[FAIL] No active ProviderDiscoveryConfig for CN")
            return

        print(f"[OK] Discovery surface: {config.discovery_surface_url}")
        print(f"[OK] Strategy: {config.discovery_strategy}")

        # Build UniversityStrategy
        university_strategy = UniversityStrategy(
            country=country,
            surface_url=config.discovery_surface_url,
        )

        # Run CountryEcosystemDiscovery
        print("\n[INFO] Starting ecosystem discovery for CN (University vertical slice)...")
        engine = CountryEcosystemDiscovery(session)
        metrics = await engine.discover(country, strategies=[university_strategy])

        # Report metrics
        print("\n[METRICS] Discovery Metrics:")
        print(f"  Strategies executed: {metrics.strategies_executed}")
        print(f"  Organizations discovered: {metrics.organizations_discovered}")
        print(f"  Organizations created: {metrics.organizations_created}")
        print(f"  Organizations updated: {metrics.organizations_updated}")
        print(f"  Duplicates skipped: {metrics.duplicates_skipped}")
        print(f"  Errors: {len(metrics.errors)}")
        if metrics.errors:
            for err in metrics.errors:
                print(f"    - {err}")

        print("\n[OK] Phase 2 vertical slice complete")

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
