"""Bootstrap providers/sources for a country, then acquire programmes.

This runner is the **provider-first** counterpart to
``run_country_exploration.py``:

    provider discovery → source registration → acquisition (page intent,
    listing guard, aggregator blocking, review boundary)

Both runners share ``AcquisitionService``, so a precision fix cannot apply to
one and not the other.

Usage::

    python scripts/run_country_coverage.py JP --plan-only
    python scripts/run_country_coverage.py JP --max-sources 20 --max-pages 10

Live runs require a local database whose name ends in ``_test`` / ``_scratch``
(or ``--allow-non-scratch``). The script writes providers, sources and
scholarship records; pointing it at the development database by accident is
how a "quick look" becomes 300 rows.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def print_plan(iso2: str) -> None:
    from services.exploration.config_loader import load_country_config

    config = load_country_config(iso2)
    print("\n" + "=" * 78)
    print(f"COUNTRY COVERAGE PLAN — {config.iso2} ({config.country_name})")
    print("=" * 78)
    print("Database:      not opened (plan-only)")
    print(f"Official TLDs: {', '.join(config.soft_domain_signals) or '—'}")
    print(f"Seed portals ({len(config.seed_urls)}):")
    for url in config.seed_urls:
        print(f"  - {url}")
    print("Phases: provider discovery → source registration → acquisition")
    print("=" * 78 + "\n")


async def run_coverage(
    iso2: str,
    max_sources: int,
    max_pages: int,
    allow_non_scratch: bool,
):
    from database.config import get_database_url
    from database.session import SessionLocal
    from services.exploration.run_guard import assert_scratch_database
    from services.ingestion.country_coverage_orchestrator import (
        CountryCoverageOrchestrator,
    )

    assert_scratch_database(get_database_url(), allow_non_scratch=allow_non_scratch)

    session = SessionLocal()
    try:
        orchestrator = CountryCoverageOrchestrator(iso2, session)
        metrics = await orchestrator.run_full_coverage(
            run_provider_discovery=True,
            run_scholarship_discovery=True,
            max_urls_per_source=max_pages,
            max_sources=max_sources,
        )

        print("\n" + "=" * 80)
        print(f"COUNTRY COVERAGE REPORT - {iso2}")
        print("=" * 80)
        for key, value in metrics.to_dict().items():
            print(f"{key}: {value}")
        print("=" * 80)

        return metrics
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run country coverage for Polaris")
    parser.add_argument("iso2", help="Country ISO2 code, e.g. JP")
    parser.add_argument("--plan-only", action="store_true", help="Print the plan and exit (no DB, no network)")
    parser.add_argument("--max-sources", type=int, default=20, help="Max sources to acquire from")
    parser.add_argument("--max-pages", type=int, default=10, help="Max pages per source")
    parser.add_argument(
        "--allow-non-scratch",
        action="store_true",
        help="Permit a live run against a database not named _test/_scratch (writes!)",
    )
    args = parser.parse_args()

    if args.plan_only:
        print_plan(args.iso2.upper())
        return

    asyncio.run(
        run_coverage(
            args.iso2.upper(),
            max_sources=args.max_sources,
            max_pages=args.max_pages,
            allow_non_scratch=args.allow_non_scratch,
        )
    )


if __name__ == "__main__":
    main()
