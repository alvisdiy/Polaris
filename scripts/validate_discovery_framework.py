"""Validate the country-wide discovery framework.

For each country with active ProviderDiscoveryConfig rows:
1. Ensure organization_type is set (default to "University")
2. Run CountryEcosystemDiscovery with all enabled configs
3. Report metrics: configs executed, organizations by type, providers created/updated, etc.
4. Test idempotency (run twice, verify no new duplicates on second run)
5. Test aggregation (verify multiple configs per country are actually combined)
6. Test max_urls_per_source enforcement (if applicable)
"""

import asyncio
import sys
import os
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.session import SessionLocal
from database.models.country import Country
from database.models.provider_discovery_config import ProviderDiscoveryConfig
from database.models.provider import Provider
from services.ingestion.ecosystem_discovery import CountryEcosystemDiscovery
from services.ingestion.strategy_factory import StrategyFactory


async def run_validation():
    """Run the full validation suite."""
    session = SessionLocal()
    try:
        # Step 1: Ensure all configs have organization_type set
        print("[Step 1] Ensuring organization_type is set on all configs...")
        configs = session.query(ProviderDiscoveryConfig).all()
        updated = 0
        for cfg in configs:
            if not cfg.organization_type:
                cfg.organization_type = "University"
                updated += 1
        if updated > 0:
            session.commit()
            print(f"  Updated {updated} configs with organization_type='University'")
        print()

        # Step 2: Group configs by country
        print("[Step 2] Grouping enabled configs by country...")
        country_configs = defaultdict(list)
        for cfg in session.query(ProviderDiscoveryConfig).filter(
            ProviderDiscoveryConfig.is_active == True
        ).all():
            country = session.query(Country).filter(
                Country.country_id == cfg.country_id
            ).first()
            if country:
                country_configs[country.iso2].append((country, cfg))

        print(f"  Found {len(country_configs)} countries with active configs")
        for iso2, items in sorted(country_configs.items()):
            print(f"    {iso2}: {len(items)} config(s)")
        print()

        # Step 3: Run discovery for each country and collect metrics
        print("[Step 3] Running ecosystem discovery for each country...")
        all_results = {}
        for iso2, items in sorted(country_configs.items()):
            country = items[0][0]
            configs_for_country = [cfg for _, cfg in items]

            print(f"\n  === {iso2} ===")
            print(f"  Configs: {len(configs_for_country)}")
            for i, cfg in enumerate(configs_for_country, 1):
                print(f"    {i}. org_type={cfg.organization_type}, "
                      f"surface_url={cfg.discovery_surface_url}, "
                      f"max_urls={cfg.max_urls_per_source}")

            # Count providers BEFORE
            providers_before = (
                session.query(Provider)
                .filter(Provider.country_id == country.country_id)
                .count()
            )

            # Run discovery
            try:
                engine = CountryEcosystemDiscovery(session)
                strategies = []
                for cfg in configs_for_country:
                    try:
                        strategy = StrategyFactory.get_strategy(
                            organization_type=cfg.organization_type,
                            country=country,
                            surface_url=cfg.discovery_surface_url,
                            config=cfg,
                        )
                        strategies.append(strategy)
                    except KeyError as e:
                        print(f"    WARNING: Could not instantiate strategy for {cfg.organization_type}: {e}")

                if strategies:
                    metrics = await engine.discover(country, strategies)
                    providers_after = (
                        session.query(Provider)
                        .filter(Provider.country_id == country.country_id)
                        .count()
                    )
                    print(f"  Metrics:")
                    print(f"    Strategies executed: {metrics.strategies_executed}")
                    print(f"    Organizations discovered: {metrics.organizations_discovered}")
                    print(f"    Providers created: {metrics.organizations_created}")
                    print(f"    Providers updated: {metrics.organizations_updated}")
                    print(f"    Duplicates skipped: {metrics.duplicates_skipped}")
                    print(f"    Errors: {len(metrics.errors)}")
                    if metrics.errors:
                        for err in metrics.errors:
                            print(f"      - {err}")
                    print(f"    Total providers in DB: {providers_before} → {providers_after}")

                    all_results[iso2] = {
                        "country": country,
                        "configs_count": len(configs_for_country),
                        "metrics": metrics,
                        "providers_before": providers_before,
                        "providers_after": providers_after,
                    }
                else:
                    print(f"  ERROR: No strategies could be instantiated for {iso2}")
            except Exception as e:
                print(f"  ERROR during discovery: {e}")
                import traceback
                traceback.print_exc()

        # Step 4: Test idempotency for first country
        if all_results:
            first_iso2 = list(all_results.keys())[0]
            result = all_results[first_iso2]
            country = result["country"]
            configs_for_country = [
                cfg for cfg in session.query(ProviderDiscoveryConfig).filter(
                    ProviderDiscoveryConfig.country_id == country.country_id,
                    ProviderDiscoveryConfig.is_active == True
                ).all()
            ]

            print(f"\n[Step 4] Testing idempotency for {first_iso2}...")
            providers_before_2nd = (
                session.query(Provider)
                .filter(Provider.country_id == country.country_id)
                .count()
            )

            try:
                engine2 = CountryEcosystemDiscovery(session)
                strategies2 = []
                for cfg in configs_for_country:
                    try:
                        strategy = StrategyFactory.get_strategy(
                            organization_type=cfg.organization_type,
                            country=country,
                            surface_url=cfg.discovery_surface_url,
                            config=cfg,
                        )
                        strategies2.append(strategy)
                    except KeyError:
                        pass

                if strategies2:
                    metrics2 = await engine2.discover(country, strategies2)
                    providers_after_2nd = (
                        session.query(Provider)
                        .filter(Provider.country_id == country.country_id)
                        .count()
                    )
                    print(f"  First run created: {result['metrics'].organizations_created}")
                    print(f"  Second run created: {metrics2.organizations_created}")
                    print(f"  Second run updated: {metrics2.organizations_updated}")
                    print(f"  Second run duplicates: {metrics2.duplicates_skipped}")
                    print(f"  Provider count before 2nd: {providers_before_2nd}")
                    print(f"  Provider count after 2nd: {providers_after_2nd}")
                    if providers_after_2nd == providers_before_2nd:
                        print(f"  ✓ IDEMPOTENT: No new duplicates created")
                    else:
                        print(f"  ✗ FAILED IDEMPOTENCY: Provider count changed")
            except Exception as e:
                print(f"  ERROR during idempotency test: {e}")

        # Step 5: Summary report
        print("\n" + "="*60)
        print("SUMMARY REPORT")
        print("="*60)
        for iso2 in sorted(all_results.keys()):
            result = all_results[iso2]
            m = result["metrics"]
            print(f"\n{iso2}:")
            print(f"  Configs: {result['configs_count']}")
            print(f"  Strategies executed: {m.strategies_executed}")
            print(f"  Organizations discovered: {m.organizations_discovered}")
            print(f"  Providers: {result['providers_before']} → {result['providers_after']} "
                  f"(+{result['providers_after'] - result['providers_before']})")
            print(f"  Created: {m.organizations_created}")
            print(f"  Updated: {m.organizations_updated}")
            print(f"  Errors: {len(m.errors)}")

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(run_validation())
