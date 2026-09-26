"""Run provider discovery for a country."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import time
from database.models.country import Country
from database.session import SessionLocal
from services.ingestion.provider_discovery import ProviderDiscoveryOrchestrator


async def run_discovery(iso2: str):
    """Run provider discovery for a given country code."""
    session = SessionLocal()
    try:
        # Verify country exists
        country = session.query(Country).filter_by(iso2=iso2).first()
        if not country:
            print(f"[ERROR] Country {iso2} not found in database")
            return False

        print(f"[INFO] Starting provider discovery for {country.name} ({iso2})")
        start_time = time.time()

        orchestrator = ProviderDiscoveryOrchestrator(session)
        metrics = await orchestrator.discover_providers_for_country(iso2)

        elapsed = time.time() - start_time

        # Print summary
        print("\n" + "="*60)
        print(f"PROVIDER DISCOVERY RESULTS - {iso2}")
        print("="*60)
        print(f"Country: {country.name}")
        print(f"Duration: {elapsed:.1f} seconds")
        print(f"Discovery surfaces processed: {metrics.discovery_surfaces_processed}")
        print(f"Candidate URLs found: {metrics.candidate_urls_found}")
        print(f"After TLD filter: {metrics.candidates_after_tld_filter}")
        print(f"After keyword filter: {metrics.candidates_after_keyword_filter}")
        print(f"Auto-verified (high confidence): {metrics.verification_passed}")
        print(f"Pending human review: {metrics.verification_pending_review}")
        print(f"Duplicates skipped: {metrics.duplicates_skipped}")
        print(f"New providers created: {metrics.providers_created}")
        print(f"Existing providers updated: {metrics.providers_updated}")
        print(f"Sources registered: {metrics.sources_registered}")
        if metrics.errors:
            print(f"Errors encountered: {len(metrics.errors)}")
            for err in metrics.errors[:5]:  # Show first 5 errors
                print(f"  - {err}")
        print("="*60)

        # Optionally show pending candidates
        if metrics.verification_pending_review > 0:
            print("\n[INFO] Candidates requiring human review:")
            print("       Run review scripts or check provider table where verification_status='candidate'")

        return True

    except Exception as e:
        print(f"[ERROR] Provider discovery failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        session.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/run_provider_discovery.py <ISO2>")
        print("Example: python scripts/run_provider_discovery.py JP")
        sys.exit(1)

    iso2 = sys.argv[1].upper()
    success = asyncio.run(run_discovery(iso2))
    sys.exit(0 if success else 1)