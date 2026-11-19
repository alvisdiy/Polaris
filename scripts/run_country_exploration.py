"""Run the Country Exploration Engine for one country.

Usage:
    python scripts/run_country_exploration.py JP --plan-only
    python scripts/run_country_exploration.py JP --dry-run --report
    python scripts/run_country_exploration.py JP --report --max-runtime 15

Three modes, with different promises:

``--plan-only``
    Print the query plan and configuration, then exit. No database is opened
    and no network call is made. This is the mode to use when you want to see
    what a run *would* ask for.

``--dry-run``
    Execute the engine offline — NullSearchProvider, a fetcher that refuses to
    fetch, and a session bound to an outer transaction that is rolled back at
    the end. Nothing is written and nothing is fetched; the run exercises the
    control flow and prints metrics.

A live run (neither flag) writes. It refuses to start unless DATABASE_URL
points at a local database whose name ends in ``_test`` / ``_testing`` /
``_scratch``, or the operator passes ``--allow-non-scratch`` (or sets
``POLARIS_ALLOW_NON_SCRATCH=1``). The guard exists because a live run commits
frontier, source and scholarship rows as it goes.

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


def build_plan(iso2: str, max_runtime: int | None = None, run_offset: int = 0):
    """Load the country config and build its query plan.

    Pure: no database, no network, no provider construction. Plan-only mode
    and the live path share this so the plan someone inspects is the plan a
    run would execute.
    """
    from services.exploration.config_loader import load_country_config
    from services.exploration.query_generation import QueryGenerator

    config = load_country_config(iso2)
    if max_runtime is not None:
        config.bounds.max_runtime_minutes = max_runtime
    plan = QueryGenerator(config).generate_plan(run_offset=run_offset)
    return config, plan


def print_plan(config, plan) -> None:
    """Print what a run would ask for, without opening anything."""
    provider = os.getenv("POLARIS_SEARCH_PROVIDER", "ddgs").strip().lower()
    bounds = config.bounds
    print("\n" + "=" * 78)
    print(f"COUNTRY EXPLORATION PLAN — {config.iso2} ({config.country_name})")
    print("=" * 78)
    print("Database:      not opened (plan-only)")
    print(f"Search:        {provider}")
    print(f"Locale:        {config.search_locale} (gl={config.search_gl or 'unset'})")
    print(f"Languages:     {', '.join(config.languages)}")
    print(
        "Bounds:        "
        f"max_pages={bounds.max_pages}, max_depth={bounds.max_depth}, "
        f"per_domain={bounds.max_pages_per_domain}, "
        f"max_candidates={bounds.max_candidates}, "
        f"runtime={bounds.max_runtime_minutes}m"
    )
    print(f"Queries ({len(plan)}):")
    for index, planned in enumerate(plan, start=1):
        print(f"  {index:2d}. [{planned.family}] {planned.text}")
    print("=" * 78 + "\n")


def _rollback_only_session():
    """A session whose writes never reach the database.

    `join_transaction_mode="create_savepoint"` turns the engine's own
    ``session.commit()`` calls into SAVEPOINT releases inside the outer
    transaction, so the teardown rollback discards everything.
    """
    from database.session import SessionLocal, get_engine

    connection = get_engine().connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    return session, connection, transaction


class _OfflineAnalyzer:
    """Fetcher used by --dry-run: never makes a network request.

    Returns the same shape as CandidateAnalyzer so the engine's control flow is
    exercised exactly as in a live run. ``max_retries`` is forced to zero in
    dry-run, so a refused fetch is terminal rather than retried three times.
    """

    async def analyze(self, url: str):
        from services.exploration.candidate_analyzer import AnalyzedCandidate

        return AnalyzedCandidate(url=url, error="dry_run_offline")


def _cleanup(session, connection, transaction):
    """Return a callable that releases the run's database resources."""

    def cleanup() -> None:
        if session is not None:
            session.close()
        if transaction is not None:
            transaction.rollback()
        if connection is not None:
            connection.close()

    return cleanup


async def run_exploration(
    iso2: str,
    dry_run: bool,
    max_runtime: int | None,
    allow_non_scratch: bool = False,
):
    """Run one exploration and return ``(engine, metrics, cleanup)``.

    The caller prints the report *before* calling ``cleanup``: a dry-run's
    session is bound to an explicit connection, and closing that connection
    first would make the report's own queries fail with
    ``ResourceClosedError``. A live session survives close() by re-acquiring
    from the pool, which is why the difference only shows up in dry-run.
    """
    from services.exploration.engine import CountryExplorationEngine
    from services.exploration.search import NullSearchProvider, create_search_provider

    config, _ = build_plan(iso2, max_runtime=max_runtime)

    session = None
    connection = None
    transaction = None
    cleanup = _cleanup(session, connection, transaction)
    try:
        if dry_run:
            config.bounds.max_retries = 0
            search_provider = NullSearchProvider()
            session, connection, transaction = _rollback_only_session()
            cleanup = _cleanup(session, connection, transaction)
            logger.info("Dry-run mode: offline, no writes (transaction will be rolled back)")
            analyzer = _OfflineAnalyzer()
        else:
            from database.config import get_database_url
            from services.exploration.run_guard import assert_scratch_database

            assert_scratch_database(
                get_database_url(), allow_non_scratch=allow_non_scratch
            )
            search_provider = create_search_provider()
            if getattr(search_provider, "configured", True) is False:
                logger.warning(
                    "Search provider not configured (POLARIS_SERPER_API_KEY missing) — "
                    "web search will be degraded; seeds/known sources/expansion still work."
                )
            from database.session import SessionLocal

            session = SessionLocal()
            cleanup = _cleanup(session, connection, transaction)
            analyzer = None

        engine = CountryExplorationEngine(session, config, search_provider, analyzer=analyzer)
        metrics = await engine.run()
        # Snapshot DB-backed values while the session is live: run() ends with
        # a commit that expires ORM attributes, and close() detaches them —
        # printing afterwards would crash on lazy refresh (observed live).
        engine.final_frontier_states = engine.frontier.count_by_state(
            engine.country.country_id
        )
        return engine, metrics, cleanup
    except Exception:
        cleanup()
        raise


def print_review_metrics(engine) -> None:
    """Print the M9 curation queue for the country that was just explored.

    Reported separately from the run counters because the run's metrics are
    this run's work, while these are the standing backlog. An exploration run
    that persists 20 records does not curate them: they sit in the queue until
    a reviewer approves them, and that separation is the whole point of the
    publication boundary.
    """
    from services.review import ReviewService

    session = engine.session
    review = ReviewService(session)
    country_id = str(engine.country.country_id)
    stats = review.metrics(country_id=country_id)

    print("\n" + "-" * 78)
    print(f"CURATION QUEUE — {engine.config.iso2}")
    print("-" * 78)
    print(f"Scholarships total:        {stats['total']}")
    print(f"Pending review:            {stats['pending_review']}")
    print(f"Approved (published):      {stats['approved']}")
    print(f"Rejected:                  {stats['rejected']}")
    print(f"Needs correction:          {stats['needs_correction']}")
    print(
        f"Approval rate:             {stats['approval_rate']} "
        f"(rejection: {stats['rejection_rate']})"
        if stats["approval_rate"] is not None
        else "Approval rate:             n/a (nothing decided yet)"
    )
    print(f"By provenance origin:      {stats['by_origin']}")
    print(f"Records with conflicts:    {stats['records_with_conflicts']}")
    print(f"Low-confidence extracts:   {stats['low_confidence_extractions']}")

    pending, _ = review.list_for_review(
        state="pending_review", country_id=country_id, limit=5
    )
    if pending:
        print("\nSample awaiting review (name / confidence / blocking gates):")
        for row in pending:
            summary = review.queue_summary(row)
            confidence = summary["extraction_confidence"]
            gates = ", ".join(summary["blocking_fields"]) or "none"
            print(f"  - {summary['scholarship_name']!r}  confidence={confidence}  gates={gates}")
    print("-" * 78)


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
    if m.get("search_degraded_reason"):
        print(f"Search degraded:           {m['search_degraded_reason']}")
    if m.get("search_failure_categories"):
        print(f"Search failure categories:  {m['search_failure_categories']}")
    print(f"Search results received:   {m['search_results']}")
    print(f"Aggregator leads skipped:  {m.get('aggregator_candidates_skipped', 0)}")
    print(f"Candidates created:        {m['candidates_created']} (dedup merges: {engine.frontier.dedup_merges})")
    print(f"Candidates by origin:      {m['candidates_by_origin']}")
    print(f"Candidates by type:        {m.get('candidates_by_type')}")
    print(
        f"Candidates rejected by bounds: {engine.frontier.rejected_by_bounds} "
        f"(admitted: {engine.frontier.admitted})"
    )
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
    print(
        f"Scholarships persisted:    {m['scholarships_persisted']} "
        f"(duplicates collapsed: {m['duplicates_collapsed']})"
    )
    print(
        f"Extraction failures:       {m['extraction_failures']} "
        f"(acquisition failures: {m.get('acquisition_failures', 0)})"
    )
    print(f"Link expansions:           {m['link_expansions']}")
    print(f"Retries:                   {m['retries']}")
    runtime = getattr(engine, "metrics_dict", {}).get(
        "runtime_seconds", m.get("runtime_seconds", "?")
    )
    print(f"Runtime:                   {runtime}s")
    print(f"Frontier states:           {frontier_states}")

    # Curation state, read back from the database rather than from this run's
    # counters: the run's numbers say what happened, these say what survived.
    print_review_metrics(engine)
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
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Print the query plan and exit (no database, no network)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run offline with no fetching and roll every write back",
    )
    parser.add_argument("--max-runtime", type=int, default=None, help="Override max runtime (minutes)")
    parser.add_argument(
        "--allow-non-scratch",
        action="store_true",
        help="Permit a live run against a database not named _test/_scratch (writes!)",
    )
    args = parser.parse_args()

    if args.plan_only:
        config, plan = build_plan(args.iso2, max_runtime=args.max_runtime)
        print_plan(config, plan)
        return

    engine, metrics, cleanup = asyncio.run(
        run_exploration(
            args.iso2,
            args.dry_run,
            args.max_runtime,
            allow_non_scratch=args.allow_non_scratch,
        )
    )

    try:
        if args.dry_run:
            print("\n(dry-run: every write above was rolled back; nothing was fetched)\n")

        if args.report:
            print_report(engine, metrics)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
