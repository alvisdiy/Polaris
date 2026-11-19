"""Run the whole scholarship pipeline for one or more countries, unattended.

This is the command a scheduler calls. It is the only supported entry point for
"keep the catalogue growing", and it deliberately contains no decisions that
need a person or a model:

    1. ensure the country's configured seed portals are registered as sources
    2. optionally discover more providers from the country's own surfaces
    3. crawl the active sources within a page budget
    4. fill empty fields from the documents just stored (deterministic)
    5. print a report and write a JSON run record

Every step is bounded, resumable and idempotent. Running it twice in a row
crawls nothing new, fills nothing new, and changes no records — which is what
makes it safe to put on a nightly schedule.

    python scripts/pipeline_run.py MY BN DE --max-total-pages 150
    python scripts/pipeline_run.py MY --discover --runtime 25
    python scripts/pipeline_run.py --all --skip-recent-days 7

Windows Task Scheduler / cron:

    0 3 * * *  cd /path/to/polaris && .venv/bin/python scripts/pipeline_run.py --all

Exit codes: 0 success, 1 at least one country failed, 2 bad invocation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _configured_countries() -> list[str]:
    root = Path(__file__).resolve().parents[1] / "configs" / "countries"
    return sorted(path.stem.upper() for path in root.glob("*.json"))


def _plan(countries: list[str], args) -> None:
    from services.exploration.config_loader import load_country_config

    print("=" * 70)
    print("POLARIS PIPELINE PLAN")
    print("=" * 70)
    for iso2 in countries:
        try:
            config = load_country_config(iso2)
        except FileNotFoundError:
            print(f"  {iso2}: NO CONFIG")
            continue
        print(f"  {iso2} {config.country_name}: {len(config.seed_urls)} seed portal(s)")
        for url in config.seed_urls:
            print(f"      - {url}")
    print("\nSteps per country: seeds → discover (optional) → crawl → enrich → auto-review")
    print(f"Budget: {args.max_total_pages} page(s), {args.runtime} minute(s) per country")
    print("Database: not opened (plan-only)")


async def _run_country(iso2: str, args) -> dict:
    from database.session import SessionLocal
    from scripts.run_country_crawl import crawl_country, ensure_seed_sources

    record: dict = {"iso2": iso2, "steps": {}, "errors": []}

    session = SessionLocal()
    try:
        try:
            seeded = ensure_seed_sources(session, iso2)
        except Exception as exc:  # a broken config must not stop the other countries
            record["errors"].append(f"seed: {type(exc).__name__}: {exc}")
            seeded = 0
        record["steps"]["seeded_sources"] = seeded
    finally:
        session.close()

    if args.discover:
        from services.ingestion.country_coverage_orchestrator import (
            CountryCoverageOrchestrator,
        )

        session = SessionLocal()
        try:
            orchestrator = CountryCoverageOrchestrator(iso2, session)
            await orchestrator.run_full_coverage(
                run_provider_discovery=True,
                run_scholarship_discovery=False,
                max_sources=args.max_sources,
            )
            record["steps"]["providers_discovered"] = orchestrator.metrics.providers_discovered
            record["steps"]["sources_discovered"] = orchestrator.metrics.sources_discovered
        except Exception as exc:
            record["errors"].append(f"discover: {type(exc).__name__}: {exc}")
        finally:
            session.close()

    try:
        totals = await crawl_country(
            iso2,
            discover=False,
            max_sources=args.max_sources,
            source_id=None,
            max_pages_per_source=args.max_pages_per_source,
            max_total_pages=args.max_total_pages,
            max_runtime_minutes=args.runtime,
            skip_recent_days=args.skip_recent_days,
            allow_non_scratch=args.allow_non_scratch,
        )
        record["steps"]["crawl"] = {
            "sources": totals.sources_processed,
            "skipped": totals.sources_skipped,
            "pages": totals.pages_fetched,
            "candidates": totals.candidates,
            "extracted": totals.extraction_succeeded,
            "failed": totals.extraction_failed,
            "persisted": totals.persisted,
            "duplicates": totals.duplicates,
            "errors": totals.errors,
        }
    except Exception as exc:
        record["errors"].append(f"crawl: {type(exc).__name__}: {exc}")

    # Enrichment reads what the crawl just stored, so it runs after it and in the
    # same process: a nightly job should not need a second scheduler entry.
    try:
        from scripts import enrich_records

        class _Args:
            country = iso2
            state = "all"
            limit = 500
            dry_run = False
            fetch_missing = False
            actor = "enrichment"
            json = False

        if not args.no_enrich:
            enrich_records.run(_Args())
            record["steps"]["enrich"] = "ran"
        else:
            record["steps"]["enrich"] = "skipped"
    except Exception as exc:
        record["errors"].append(f"enrich: {type(exc).__name__}: {exc}")

    # Deterministic review: publish what passed every gate, refuse what cannot
    # become publishable, leave the rest. No model is involved, which is the
    # point — a nightly job must not depend on someone reading the queue.
    if not args.no_auto_review:
        try:
            from scripts import auto_review

            class _ReviewArgs:
                country = iso2
                limit = 500
                dry_run = False
                no_page_text = False
                actor = "auto-review"
                json = False

            auto_review.run(_ReviewArgs())
            record["steps"]["auto_review"] = "ran"
        except Exception as exc:
            record["errors"].append(f"auto_review: {type(exc).__name__}: {exc}")
    else:
        record["steps"]["auto_review"] = "skipped"

    return record


async def _main(args) -> int:
    countries = args.countries or (_configured_countries() if args.all else [])
    countries = [c.upper() for c in countries]
    if not countries:
        print("no countries given; pass ISO2 codes or --all", file=sys.stderr)
        return 2

    if args.plan_only:
        _plan(countries, args)
        return 0

    started = datetime.now(timezone.utc)
    records = []
    for iso2 in countries:
        print(f"\n{'=' * 70}\nPIPELINE — {iso2}\n{'=' * 70}")
        records.append(await _run_country(iso2, args))

    print("\n" + "=" * 70)
    print("PIPELINE SUMMARY")
    print("=" * 70)
    header = f"{'ISO':<4}{'seeds':>7}{'pages':>7}{'extr':>6}{'new':>6}{'dup':>6}{'errors':>7}"
    print(header)
    total_new = 0
    failures = 0
    for record in records:
        crawl = record["steps"].get("crawl", {})
        total_new += crawl.get("persisted", 0)
        if record["errors"]:
            failures += 1
        print(
            f"{record['iso2']:<4}"
            f"{record['steps'].get('seeded_sources', 0):>7}"
            f"{crawl.get('pages', 0):>7}"
            f"{crawl.get('extracted', 0):>6}"
            f"{crawl.get('persisted', 0):>6}"
            f"{crawl.get('duplicates', 0):>6}"
            f"{len(record['errors']) + crawl.get('errors', 0):>7}"
        )
        for error in record["errors"]:
            print(f"     ! {error}")

    finished = datetime.now(timezone.utc)
    summary = {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "countries": records,
        "new_records": total_new,
        "countries_with_errors": failures,
    }
    if args.json:
        print(json.dumps(summary, indent=2, default=str))

    out_dir = Path(__file__).resolve().parents[1] / ".zwork" / "pipeline_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nrun record: {out_path}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("countries", nargs="*", help="ISO2 codes, e.g. MY BN DE")
    parser.add_argument("--all", action="store_true", help="Every country with a config")
    parser.add_argument("--discover", action="store_true", help="Run provider discovery first")
    parser.add_argument("--plan-only", action="store_true", help="Print the plan, open no database")
    parser.add_argument("--no-enrich", action="store_true", help="Skip deterministic completion")
    parser.add_argument(
        "--no-auto-review",
        action="store_true",
        help="Skip the deterministic review pass (records stay pending)",
    )
    parser.add_argument("--max-sources", type=int, default=25)
    parser.add_argument("--max-pages-per-source", type=int, default=10)
    parser.add_argument("--max-total-pages", type=int, default=150)
    parser.add_argument("--runtime", type=int, default=20, help="Minutes per country")
    parser.add_argument("--skip-recent-days", type=int, default=0)
    parser.add_argument("--allow-non-scratch", action="store_true")
    parser.add_argument("--json", action="store_true")
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
