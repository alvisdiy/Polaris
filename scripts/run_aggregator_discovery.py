"""Run a bounded aggregator acquisition batch against an isolated database.

Discovery can run without a database. Persistence requires an explicit local
PostgreSQL URL in POLARIS_AGGREGATOR_TEST_DATABASE_URL whose database name ends
in `_test` or `_scratch`; this command never falls back to DATABASE_URL and
never creates, drops, or migrates tables.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections import Counter

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from services.aggregator_discovery.adapters import (
    discover_configured_source,
    load_aggregator_sources,
)


def isolated_database_url() -> URL:
    value = os.environ.get("POLARIS_AGGREGATOR_TEST_DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError(
            "Set POLARIS_AGGREGATOR_TEST_DATABASE_URL to a disposable local PostgreSQL database."
        )
    url = make_url(value)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("Aggregator persistence requires PostgreSQL.")
    if url.host not in (None, "localhost", "127.0.0.1", "::1"):
        raise RuntimeError("Refusing a non-local database host.")
    if not re.search(r"(?:_test|_scratch)$", url.database or "", re.IGNORECASE):
        raise RuntimeError("Database name must end with _test or _scratch.")
    return url


async def run(*, discover_only: bool, article_limit: int) -> int:
    sources = load_aggregator_sources()
    if discover_only:
        for source in sources:
            candidates = await discover_configured_source(source)
            print(f"{source.id}: {len(candidates)} unique article candidates")
            for candidate in candidates[:article_limit]:
                print(f"  {candidate.title or '(untitled)'} | {candidate.canonical_url}")
        return 0

    database_url = isolated_database_url()
    # Import only after the scratch target is explicitly validated. No ORM
    # metadata creation or migration is run by this command.
    from services.aggregator_discovery.ingestion import run_configured_source

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            for source in sources:
                outcomes = await run_configured_source(
                    session, source, article_limit=article_limit
                )
                states = Counter(outcome.state for outcome in outcomes)
                print(f"{source.id}: {len(outcomes)} processed; states={dict(states)}")
                for outcome in outcomes:
                    print(
                        f"  {outcome.state} | {outcome.article_url} | "
                        f"official={outcome.official_url or 'unresolved'} | "
                        f"blockers={','.join(outcome.blockers) or 'none'}"
                    )
    finally:
        engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Fetch configured archive pages and list candidates without opening a database.",
    )
    parser.add_argument(
        "--article-limit",
        type=int,
        default=3,
        help="Maximum articles processed per aggregator (bounded to 1..50).",
    )
    args = parser.parse_args()
    if not 1 <= args.article_limit <= 50:
        parser.error("--article-limit must be between 1 and 50")
    return asyncio.run(run(discover_only=args.discover_only, article_limit=args.article_limit))


if __name__ == "__main__":
    raise SystemExit(main())
