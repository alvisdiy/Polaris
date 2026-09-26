"""Run complete country coverage for a given country.

This is the single entry-point for:
  Country
  → Provider Discovery
  → Provider Verification
  → Source Discovery
  → Source Verification
  → Scholarship Discovery
  → Acquisition
  → Extraction
  → Validation
  → Deduplication
  → Persistence
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from services.ingestion.country_coverage_orchestrator import CountryCoverageOrchestrator


async def run_coverage(iso2: str):
    session = SessionLocal()
    try:
        orchestrator = CountryCoverageOrchestrator(iso2, session)
        metrics = await orchestrator.run_full_coverage(
            run_provider_discovery=True,
            run_scholarship_discovery=True,
            max_urls_per_source=50,
        )

        print("\n" + "=" * 80)
        print(f"COUNTRY COVERAGE REPORT - {iso2}")
        print("=" * 80)
        for k, v in metrics.to_dict().items():
            print(f"{k}: {v}")
        print("=" * 80)

        return metrics
    finally:
        session.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_country_coverage.py <ISO2>")
        print("Example: python scripts/run_country_coverage.py JP")
        sys.exit(1)

    iso2 = sys.argv[1].upper()
    asyncio.run(run_coverage(iso2))
