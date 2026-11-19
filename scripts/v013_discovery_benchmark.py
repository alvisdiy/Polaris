"""Real Scholarship Discovery Benchmark — controlled multi-country experiment.

Answers one question with measurement rather than assertion:

    Did the Scholarship Discovery Expansion (7 query families) actually
    discover more distinct scholarships than the previous 4-family plan?

    python scripts/v013_discovery_benchmark.py                  # read-only report
    python scripts/v013_discovery_benchmark.py --run KR GB ID SG
    python scripts/v013_discovery_benchmark.py --countries GB ID

This is an **experiment**, not a tuning session. Nothing here alters query
templates, thresholds, page-intent rules, the listing guard, extraction, dedup,
crawl depth or the frontier budget. The engine is driven exactly as
`scripts/run_country_exploration.py` drives it; the only thing this script
adds is a manifest so a run can be reproduced and attributed afterwards.

Measurement rules this script now enforces (see
`docs/progress/V013-BENCHMARK-HARNESS-AUDIT.md`):

1. **Every funnel metric is scoped to a run.** Metrics persisted by the engine
   at run finalise are read from `exploration_run.metrics`; anything derived
   from the database is filtered through the run's actual lineage. Nothing is
   reported as a run result because it happens to be a corpus total.

2. **Query attribution is resolved from immutable observations.** A frontier
   row is one logical URL and its `origin_query` column is frozen at first
   discovery, so reading it attributes a run's work to whichever run got there
   first. Attribution therefore reads `evidence.observations`, filtering to the
   run being measured.

3. **Uniqueness is canonical identity.** `COUNT(DISTINCT identity_key)`, the
   production key from `services.scholarship.identity`. Row count is never a
   proxy for uniqueness.

4. **Approval is never inferred.** `ReviewService` does not approve
   automatically, so `approved` is reported only for the run's own new
   scholarships and, separately, as a clearly labelled all-time snapshot.

5. **Repeated queries are disclosed.** Rotation intentionally revisits queries;
   that is not new coverage, so the overlap with prior runs is measured and
   printed rather than counted as breadth.

Live execution requires `--run` and `POLARIS_SERPER_API_KEY`. The key name
matters: the provider reads `POLARIS_SERPER_API_KEY`
(services/exploration/search/serper.py), and an earlier version of this script
checked for `SERPER_API_KEY`, which would have refused a correctly configured
system.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Direct invocation (`python scripts/v013_discovery_benchmark.py`) puts
# scripts/ on sys.path, not the project root, so every `database`/`services`
# import failed. pytest passes because pythonpath = ["."]. Same bootstrap as
# scripts/run_country_exploration.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402
from services.exploration import benchmark_metrics as bm  # noqa: E402

load_dotenv(".env")

MANIFEST_PATH = Path("docs/progress/benchmark_runs.json")

# The 10 runs recorded before the expansion used 4 families. Anything this
# harness executed is tagged with the new plan identifier, so a re-run months
# later still labels itself correctly without comparing timestamps.
PLAN_NEW = "7_family_expansion"

NOT_MEASURABLE = "NOT MEASURABLE FROM CURRENT DATA"


# --------------------------------------------------------------- manifest


def _plan_signature(config, conn=None) -> dict:
    """The exact query plan this run will execute, hashed for reproducibility."""
    from services.exploration.query_generation import QueryGenerator

    # run_offset is the count of prior runs for the country, so the plan a run
    # executes is a function of persisted state, not of the wall clock.
    own = SessionLocal()
    try:
        from sqlalchemy import func

        from database.models.country import Country
        from database.models.exploration_run import ExplorationRun

        country = own.query(Country).filter(Country.iso2 == config.iso2.upper()).first()
        prior = (
            own.query(func.count())
            .filter(ExplorationRun.country_id == country.country_id)
            .scalar()
            or 0
        )
        country_id = str(country.country_id)
    finally:
        own.close()

    plan = QueryGenerator(config).generate_plan(run_offset=int(prior) + 1)
    families = Counter(q.family for q in plan)
    signature = {
        "country": config.iso2.upper(),
        # The engine counts runs AFTER ``RunRepository.start_run`` has already
        # committed its own row, so the offset it actually rotates to is
        # ``prior + 1``. Recording ``prior`` here produced a plan that was never
        # executed: measured against the 2026-10-04 batch, 43 of 48 executed
        # queries (90%) had no family mapping at all, and GB resolved 0%.
        "run_offset_before_run": int(prior),
        "run_offset_used_by_engine": int(prior) + 1,
        "plan_hash": hashlib.sha256(
            "|".join(sorted(q.text for q in plan)).encode("utf-8")
        ).hexdigest(),
        "query_count": len(plan),
        "distinct_query_count": len({q.text for q in plan}),
        "families": dict(sorted(families.items())),
        "queries": {q.text: q.family for q in plan},
        "bounds": config.bounds.model_dump(),
        "plan_identifier": PLAN_NEW,
    }

    # B3: measure how much of this plan is genuinely new surface. Rotation is
    # intentional, so a repeat is not waste -- but it is not breadth either,
    # and a report that counts it as breadth overstates the run.
    if conn is not None:
        signature["query_repetition"] = bm.query_repetition(
            conn, country_id, signature["queries"]
        )
    return signature


def _load_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _save_manifest(entries: list[dict]) -> None:
    MANIFEST_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")


# ------------------------------------------------------------------- run


def _run_country(iso2: str, max_runtime: int) -> dict:
    from scripts.run_country_exploration import run_exploration
    from services.exploration.config_loader import load_country_config

    config = load_country_config(iso2)

    probe = SessionLocal()
    try:
        signature = _plan_signature(config, probe.connection())
    finally:
        probe.close()

    print(
        f"\n{'=' * 78}\n{iso2}: {signature['query_count']} queries "
        f"across {len(signature['families'])} families, "
        f"plan_hash={signature['plan_hash'][:12]}\n{'=' * 78}",
        flush=True,
    )

    started = datetime.now(timezone.utc)
    engine, metrics = asyncio.run(run_exploration(iso2, dry_run=False, max_runtime=max_runtime))
    finished = datetime.now(timezone.utc)

    persisted = dict(engine.metrics.__dict__)
    frontier_states = getattr(engine, "final_frontier_states", {}) or {}

    # `engine.current_run` is the ExplorationRun row the engine publishes after
    # start_run. It is not named `run` on the engine because that would shadow
    # the run() method. Read defensively rather than by getattr chain: a missing
    # run must be reported as a missing run, not as an attribute error that
    # hides the fact that no run-scoped metric can be derived.
    run_row = getattr(engine, "current_run", None)
    if run_row is None or callable(run_row):
        run_id = status = None
        run_scope_measurable = False
    else:
        run_id = getattr(run_row, "run_id", None)
        status = getattr(run_row, "status", None)
        run_scope_measurable = run_id is not None

    record = {
        "country": iso2,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "plan": signature,
        # Recorded explicitly so a later report can scope to this run without
        # inferring anything from timestamps. An earlier harness computed the
        # status and then dropped it, which is why a failed batch shipped as a
        # benchmark result with no way to tell.
        "run_id": str(run_id) if run_id else None,
        "run_status": status,
        # A run whose id could not be read cannot be measured run-scoped at
        # all, so the entry says so rather than looking like a run that simply
        # produced nothing.
        "run_scope_measurable": run_scope_measurable,
        "metrics": {k: v for k, v in persisted.items() if not k.startswith("_")},
        "frontier_states": {str(k): int(v) for k, v in frontier_states.items()},
    }
    return record


# -------------------------------------------------------------- reporting


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _run_scoped_report(conn, entry: dict) -> None:
    """One run's funnel, every metric scoped to that run."""
    run_id = entry.get("run_id")
    iso2 = entry.get("country", "?")
    print(f"\n{'-' * 78}\nRUN-SCOPED REPORT — {iso2}  run={run_id or '(not recorded)'}"
          f"  status={entry.get('run_status') or '(unknown)'}\n{'-' * 78}")

    if not run_id:
        print("  NO RUN SCOPE ON THIS ENTRY. The run_id could not be read, so no")
        print("  run-scoped metric can be derived from it. Two different causes")
        print("  produce this and they must not be conflated:")
        print("    * the entry predates run_id recording (historical evidence);")
        print("    * the runner failed to publish the run row (a harness defect).")
        print("  Either way it is NOT a baseline. See the run log for the status")
        print("  line the engine wrote when it finalised the run.")
        return

    funnel = bm.run_funnel(conn, run_id)
    if "error" in funnel:
        print(f"  {funnel['error']}")
        return

    print(f"{'SECTION':<14}{'METRIC':<32}{'VALUE':>10}  SOURCE")
    print("-" * 96)
    for section in ("search", "discovery", "fetch", "extraction", "identity"):
        for metric, payload in funnel[section].items():
            flag = "" if payload["recorded"] else "  (not recorded by this run)"
            print(
                f"{section:<14}{metric:<32}{_fmt(payload['value']):>10}"
                f"  {payload['source']}{flag}"
            )

    scholarships = bm.run_scholarship_funnel(conn, run_id)
    print(f"\n{'SCHOLARSHIPS':<14}{'METRIC':<32}{'VALUE':>10}  SOURCE")
    print("-" * 96)
    print(f"{'':<14}{'candidate rows from this run':<32}"
          f"{scholarships['candidate_scholarship_rows']:>10}  source_registry.discovered_via.run_id")
    print(f"{'':<14}{'NEW UNIQUE SCHOLARSHIPS':<32}"
          f"{scholarships['new_unique_scholarships']:>10}  COUNT(DISTINCT identity_key)")
    for status, count in scholarships["by_extraction_status"].items():
        print(f"{'':<14}{f'  of which {status}':<32}{count:>10}  run's own records")
    print(f"{'':<14}{'identity_key missing':<32}"
          f"{scholarships['identity_keys_missing']:>10}  must be 0")
    print(f"{'':<14}{'family attribution sum':<32}{scholarships['family_sum']:>10}"
          f"  may exceed unique (intentional)")
    print(f"\n  {scholarships['note']}")

    print(f"\n  NOT RUN-SCOPABLE: {funnel['not_run_scopable']['note']}")


def _family_report(conn, entry: dict) -> None:
    """B2/D2: which families produced this run's discovery, and its scholarships."""
    run_id = entry.get("run_id")
    if not run_id:
        return
    iso2 = entry.get("country", "?")
    buckets = bm.repeat_attribution(conn, run_id, entry["plan"]["queries"])
    if not buckets:
        print(f"\n  {iso2}: no family-attributable observations for this run.")
        return

    print(f"\n{iso2} — QUERY FAMILY ATTRIBUTION (this run's own observations)")
    print(f"{'FAMILY':<18}{'OBS':>7}{'CANDS':>8}{'DONE':>7}{'REJ':>6}{'PEND':>7}"
          f"{'NEW UNIQUE':>12}{'ROWS':>7}")
    print("-" * 72)
    scholarships = bm.run_scholarship_funnel(conn, run_id)
    for family, stats in sorted(buckets.items()):
        fam = scholarships["by_family"].get(family, {})
        print(
            f"{family:<18}{stats['observations']:>7}{stats['candidates']:>8}"
            f"{stats['done']:>7}{stats['rejected']:>6}{stats['pending']:>7}"
            f"{fam.get('unique_scholarships', 0):>12}{fam.get('scholarship_rows', 0):>7}"
        )
    print("-" * 72)
    print(f"{'TOTAL':<18}{sum(b['observations'] for b in buckets.values()):>7}"
          f"{sum(b['candidates'] for b in buckets.values()):>8}"
          f"{sum(b['done'] for b in buckets.values()):>7}"
          f"{sum(b['rejected'] for b in buckets.values()):>6}"
          f"{sum(b['pending'] for b in buckets.values()):>7}"
          f"{scholarships['new_unique_scholarships']:>12}"
          f"{scholarships['candidate_scholarship_rows']:>7}")
    print("NEW UNIQUE is the global count and never double-counts.")

    # Family attribution is a LOWER BOUND. A scholarship whose source was
    # registered by seed or known-source enqueue carries no origin_query, so no
    # family can claim it. Printing the unattributed remainder is what stops
    # the table above from reading as "these families produced nothing".
    attributed = sum(f["scholarship_rows"] for f in scholarships["by_family"].values())
    unattributed = scholarships["candidate_scholarship_rows"] - attributed
    if unattributed:
        print(
            f"\n  NOT ATTRIBUTED TO ANY FAMILY: {unattributed} of "
            f"{scholarships['candidate_scholarship_rows']} row(s).\n"
            "  These came from sources registered by seed or known-source\n"
            "  enqueue, which carry no origin_query. The family table above is\n"
            "  a lower bound, not a complete attribution."
        )


def _repetition_report(entry: dict) -> None:
    rep = entry["plan"].get("query_repetition")
    if not rep:
        return
    print(
        f"  {entry['country']}: {rep['queries_planned']} queries planned, "
        f"{rep['queries_repeated_from_previous_run']} repeated from a prior run, "
        f"{rep['queries_new_to_this_country']} new to this country"
    )


def _manifest_overview(entries: list[dict]) -> None:
    print(f"\nBENCHMARK RUNS RECORDED: {len(entries)}")
    for e in entries:
        m = e.get("metrics", {})
        print(
            f"  {e['country']:<3} plan={e['plan']['plan_hash'][:12]} "
            f"run={(e.get('run_id') or '(none)')[:8]:<9} "
            f"status={e.get('run_status') or '(unknown)':<9} "
            f"queries={m.get('queries_executed')} fetched={m.get('pages_fetched')} "
            f"extracted={m.get('extraction_succeeded')} "
            f"persisted={m.get('scholarships_persisted')} {e['duration_seconds']}s"
        )
        _repetition_report(e)


def _historical_reference(conn) -> None:
    """The pre-expansion figure, printed as a labelled reference only."""
    snapshot = bm.all_time_snapshot(conn)
    live_queries = conn.execute(
        text("SELECT coalesce(sum((metrics->>'queries_executed')::int),0) FROM exploration_run")
    ).scalar_one()
    engine_approved = snapshot["approved_by_provenance_origin"].get("exploration", 0)
    print(
        "\nHISTORICAL CONTAMINATED REFERENCE (not a baseline)\n"
        "  ~26.0 queries / approved scholarship = 1039 queries / 40 approved.\n"
        "  Contaminated on both sides:\n"
        "    denominator 40 includes records that predate the engine\n"
        f"      approved by provenance_origin: {snapshot['approved_by_provenance_origin']}\n"
        f"      only {engine_approved} approved record(s) were engine-produced\n"
        "    numerator 1039 is queries_executed, which includes\n"
        "      authority-resolution queries, not only discovery queries\n"
        f"  Live total queries_executed across ALL runs is now {live_queries}\n"
        "    (the 4 failed 2026-10-04 runs contribute to it), so it is not\n"
        "    comparable to the 1039 the 26.0 figure was derived from.\n"
        "  A clean baseline must be measured from engine-produced records only."
    )


def _corpus_snapshot(conn) -> None:
    snap = bm.all_time_snapshot(conn)
    print(f"\n{snap['scope']}")
    for key, value in snap.items():
        if key in ("scope", "approved_by_provenance_origin"):
            continue
        print(f"  {key:<28}{_fmt(value)}")
    print("  approved_by_provenance_origin:")
    for origin, count in snap["approved_by_provenance_origin"].items():
        marker = "  <- engine-produced" if origin in bm.ENGINE_PROVENANCE_ORIGINS else ""
        print(f"    {origin:<24}{count:>4}{marker}")


# ------------------------------------------------------------------- main


def _main(args) -> int:
    entries = _load_manifest()

    if args.run:
        load_dotenv(".env", override=True)
        if not os.environ.get("POLARIS_SERPER_API_KEY"):
            print("POLARIS_SERPER_API_KEY is not set. Refusing to run discovery.", flush=True)
            return 2

        for iso2 in args.run:
            record = _run_country(iso2.upper(), args.max_runtime)
            entries.append(record)
            _save_manifest(entries)
            print(
                f"  -> {iso2.upper()} recorded to {MANIFEST_PATH} "
                f"(run_id={record.get('run_id')}, status={record.get('run_status')})",
                flush=True,
            )

    session = SessionLocal()
    conn = session.connection()
    try:
        selected = entries
        if args.countries:
            wanted = {c.upper() for c in args.countries}
            selected = [e for e in entries if e.get("country", "").upper() in wanted]

        if not selected:
            print("No benchmark runs recorded yet. Use --run <ISO2...>.")
        else:
            _manifest_overview(selected)
            run_ids = [e["run_id"] for e in selected if e.get("run_id")]
            if run_ids:
                good, bad = bm.exclude_failed_runs(conn, run_ids)
                print(
                    f"\nRUN ACCOUNTING: {len(good)} completed, {len(bad)} not completed."
                )
                if bad:
                    print("  Non-completed runs are reported separately and are never")
                    print("  summed into a comparison against a clean baseline.")
            for entry in selected:
                _run_scoped_report(conn, entry)
                _family_report(conn, entry)

        _historical_reference(conn)
        _corpus_snapshot(conn)
    finally:
        session.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", nargs="*", default=None, metavar="ISO2",
                        help="execute live discovery for these countries")
    parser.add_argument("--countries", nargs="*", default=None, metavar="ISO2",
                        help="restrict the read-only report to these countries")
    parser.add_argument("--max-runtime", type=int, default=45,
                        help="per-country runtime cap in minutes")
    args = parser.parse_args()
    return _main(args)


if __name__ == "__main__":
    raise SystemExit(main())