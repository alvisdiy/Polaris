"""Run the Country Exploration Engine for one country.

Usage:
    python scripts/run_country_exploration.py JP [--report] [--dry-run] [--max-runtime 45]

Zero-seed capable: requires no providers, no sources, no provider-specific
connectors — only the country config (configs/countries/jp.json), the country
row in the reference data, and optionally a search API key.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger


async def run_exploration(iso2: str, dry_run: bool, max_runtime: int | None):
    from services.exploration.config_loader import load_country_config
    from services.exploration.engine import CountryExplorationEngine
    from services.exploration.search import create_search_provider, NullSearchProvider
    from database.session import SessionLocal

    config = load_country_config(iso2)
    if max_runtime is not None:
        config.bounds.max_runtime_minutes = max_runtime

    if dry_run:
        search_provider = NullSearchProvider()
        logger.info("Dry-run mode: using NullSearchProvider (no internet)")
    else:
        search_provider = create_search_provider()
        if getattr(search_provider, "configured", True) is False:
            logger.warning(
                "Search provider not configured (POLARIS_SERPER_API_KEY missing) — "
                "web search will be degraded; seeds/known sources/expansion still work."
            )

    session = SessionLocal()
    try:
        engine = CountryExplorationEngine(session, config, search_provider)
        metrics = await engine.run()
        # Snapshot DB-backed values while the session is live: run() ends with
        # a commit that expires ORM attributes, and close() detaches them —
        # printing afterwards would crash on lazy refresh (observed live).
        engine.final_frontier_states = engine.frontier.count_by_state(
            engine.country.country_id
        )
        return engine, metrics
    finally:
        session.close()


def print_report(engine, metrics) -> None:
    config = engine.config
    m = metrics.to_dict()
    frontier_states = getattr(engine, "final_frontier_states", None)
    if frontier_states is None:
        frontier_states = engine.frontier.count_by_state(engine.country.country_id)

    print("\n" + "=" * 78)
    print(f"COUNTRY EXPLORATION REPORT — {config.iso2} ({config.country_name})")
    print("=" * 78)
    print(
        f"Queries executed:          {m['queries_executed']} "
        f"(discovery: {m['discovery_queries']}, failed: {m['queries_failed']})"
    )
    print(f"Search results received:   {m['search_results']}")
    print(f"Candidates created:        {m['candidates_created']} (dedup merges: {engine.frontier.dedup_merges})")
    print(f"Candidates by origin:      {m['candidates_by_origin']}")
    print(f"Pages fetched:             {m['pages_fetched']} (failures: {m['fetch_failures']})")
    print(f"Classification labels:     {m['classification_labels']}")
    print(f"Jobs/visa-jobs rejected:   {m['jobs_rejected']}")
    print(f"Opportunities retained:    {m['opportunities_retained']}")
    print(f"Providers created:         {m['providers_created']}")
    print(f"Providers resolved:        {m['providers_resolved']} (needs_review: {m['providers_needs_review']})")
    print(
        f"Authority resolved:        {m['authority_resolved']} "
        f"(candidates only: {m['authority_candidates_found']}, "
        f"unresolved: {m['authority_unresolved']})"
    )
    print(f"Sources verified:          {m['sources_verified']} (needs_review: {m['sources_needs_review']})")
    print(f"Scholarships persisted:    {m['scholarships_persisted']} (duplicates collapsed: {m['duplicates_collapsed']})")
    print(f"Link expansions:           {m['link_expansions']}")
    print(f"Retries:                   {m['retries']}")
    print(f"Runtime:                   {m.get('runtime_seconds', '?')}s")
    print(f"Frontier states:           {frontier_states}")
    if m.get("provenance_samples"):
        print("\nProvenance samples:")
        for sample in m["provenance_samples"]:
            obs = sample.get("observation", {})
            print(
                f"  - {sample['url']}\n"
                f"      label={sample['label']} origin={obs.get('origin')} "
                f"query={obs.get('origin_query')} rank={obs.get('rank')} provider={obs.get('search_provider')}"
            )
    print("=" * 78 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run country exploration for Polaris")
    parser.add_argument("iso2", help="Country ISO2 code, e.g. JP")
    parser.add_argument("--report", action="store_true", help="Print the full report")
    parser.add_argument("--dry-run", action="store_true", help="Use NullSearchProvider (no internet)")
    parser.add_argument("--max-runtime", type=int, default=None, help="Override max runtime (minutes)")
    args = parser.parse_args()

    engine, metrics = asyncio.run(run_exploration(args.iso2, args.dry_run, args.max_runtime))

    if args.report:
        print_report(engine, metrics)


if __name__ == "__main__":
    main()
