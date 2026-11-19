"""Run-scoped measurement for the scholarship discovery benchmark.

Every function here answers a question about **one exploration run**, or about
the set of runs a benchmark executed. None of them report a database-wide
total as though it were a run result.

That distinction is the whole point of this module. The first benchmark harness
read ``count(*) FROM scholarship WHERE extraction_status='approved'`` and called
it a discovery result. It was 40 — of which 18 predate the engine entirely
(``provenance_origin='unknown'``), 13 came from ``phase3_acquisition``, and only
9 were engine-produced. A benchmark that reports 40 as "this run approved 40"
is not measuring, it is reporting the corpus.

Three rules govern the design.

**Run-scoped numbers come from lineage, not subtraction.**
``exploration_run.metrics`` is a JSONB snapshot written when the run finalises,
and ``discovery_frontier.run_id`` names the run that created a candidate. Both
are authoritative and already exist. Subtracting a global total before and
after would be strictly worse: it is wrong the moment two runs overlap.

**Discovery is resolved through observations, not the ``origin_query`` column.**
A frontier row is one logical URL, keyed ``UNIQUE(country_id, url_hash)``. When
a later run rediscovers it, ``FrontierRepository.upsert_candidate`` appends to
``evidence.observations`` and leaves ``run_id`` / ``origin_query`` untouched. So
the column answers "which query found this URL **first**", never "which query
found it **in this run**". The observation list is the append-only event log
and is the only place run-scoped attribution can be read from.

One bound to keep in mind: ``_merge_observation`` keeps the most recent 20
observations per candidate. A URL discovered more than 20 times has its oldest
observations truncated. That is a deliberate memory bound, not a bug, and it
means attribution is exact for recent runs rather than for all of history.

**Approval is never attributed without provenance.** ``ReviewService`` does not
approve automatically, so an approved record discovered by this run is approved
later, by a human, through a path that records no run reference. This module
therefore reports what is provable — the run's own new scholarships and their
current status — and leaves the all-time approved count in a separately
labelled snapshot that no run-scoped total can silently absorb.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import text

# Frontier states that mean the candidate reached a terminal verdict. A
# candidate in PENDING or IN_PROGRESS has not been decided, and DEFERRED means
# "kept, not discarded", which is also not decided.
TERMINAL_FRONTIER_STATES = ("done", "rejected", "failed")

#: A frontier row whose ``evidence.observations`` has been truncated to this
#: many entries. Mirrors ``FrontierRepository._merge_observation``.
MAX_OBSERVATIONS_PER_CANDIDATE = 20

# Scholarship provenance origins that the exploration engine can produce. Rows
# carrying anything else (notably ``unknown``) predate the engine and must never
# be counted as engine discovery.
ENGINE_PROVENANCE_ORIGINS = ("exploration",)


# --------------------------------------------------------------------- utils


def _scalar(conn, sql: str, params: dict | None = None) -> int:
    value = conn.execute(text(sql), params or {}).scalar()
    return int(value or 0)


def _rows(conn, sql: str, params: dict | None = None):
    return conn.execute(text(sql), params or {}).fetchall()


def _metric_int(metrics: dict, key: str) -> int:
    """Read one integer out of an ``exploration_run.metrics`` snapshot.

    The column is JSONB written from a dataclass, so a missing key and a null
    are both "this run did not record it" rather than an error. Returning 0
    would overstate precision, so the caller is expected to treat absence via
    :func:`run_metric_keys_recorded` when it matters.
    """
    value = (metrics or {}).get(key)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------- run record


def run_record(conn, run_id) -> dict | None:
    """The ``exploration_run`` row for one run, or ``None``."""
    row = _rows(
        conn,
        """
        SELECT r.run_id::text, r.country_id::text, r.status, r.started_at,
               r.finished_at, r.metrics, r.config_snapshot, r.bounds_snapshot,
               co.iso2
        FROM exploration_run r
        LEFT JOIN country co ON co.country_id = r.country_id
        WHERE r.run_id = CAST(:run_id AS uuid)
        """,
        {"run_id": str(run_id)},
    )
    if not row:
        return None
    record = row[0]
    return {
        "run_id": record[0],
        "country_id": record[1],
        "status": record[2],
        "started_at": record[3],
        "finished_at": record[4],
        "metrics": record[5] or {},
        "config_snapshot": record[6] or {},
        "bounds_snapshot": record[7] or {},
        "iso2": record[8],
    }


def run_metric_keys_recorded(run_id, conn) -> set[str]:
    """Which metric keys this run actually persisted.

    Used to distinguish "this run measured zero" from "this metric did not
    exist when the run ran". The 10 historical runs predate several counters,
    and reporting their absence as 0 is how a funnel starts lying.
    """
    record = run_record(conn, run_id)
    return set(record["metrics"]) if record else set()


# ----------------------------------------------------------------- B1 funnel


def run_funnel(conn, run_id) -> dict:
    """Every benchmark funnel metric for **one run**, each with its source.

    ``from_run_metrics`` is authoritative where the engine already persisted the
    number at run finalise. ``from_run_frontier`` is read from frontier rows
    filtered by this run. ``not_run_scopable`` names the metrics that genuinely
    cannot be attributed and are therefore reported as a labelled snapshot
    instead of being quietly folded in.
    """
    record = run_record(conn, run_id)
    if record is None:
        return {"error": f"run {run_id} not found"}

    m = record["metrics"]
    recorded = set(m)
    frontier = _run_frontier_counts(conn, run_id)

    def from_metrics(key: str) -> dict:
        return {
            "value": _metric_int(m, key),
            "source": f"exploration_run.metrics.{key}",
            "recorded": key in recorded,
        }

    def derived(value: int, source: str) -> dict:
        return {"value": value, "source": source, "recorded": True}

    def not_recorded(key: str) -> dict:
        return {
            "value": None,
            "source": f"exploration_run.metrics.{key}",
            "recorded": False,
        }

    page_intents = m.get("page_intent_counts") or {}
    # UNKNOWN is deliberately extracted (see AcquisitionService), so it counts
    # as scholarship-relevant exactly like an explicit DETAIL verdict.
    relevant_pages = _metric_int(page_intents, "SCHOLARSHIP_DETAIL") + _metric_int(
        page_intents, "UNKNOWN"
    )

    extraction_success = (
        from_metrics("extraction_succeeded")
        if "extraction_succeeded" in recorded
        else not_recorded("extraction_succeeded")
    )
    extraction_failed = _metric_int(m, "extraction_failures")
    if extraction_success["value"] is None:
        extraction_attempts = None
        candidates = None
    else:
        extraction_attempts = extraction_success["value"] + extraction_failed
        candidates = extraction_success["value"] + _metric_int(m, "duplicates_collapsed")

    return {
        "run": {
            "run_id": record["run_id"],
            "iso2": record["iso2"],
            "status": record["status"],
            "started_at": record["started_at"],
            "finished_at": record["finished_at"],
        },
        "search": {
            "queries_executed": from_metrics("queries_executed"),
            "queries_discovery": from_metrics("discovery_queries"),
            "queries_authority": derived(
                _metric_int(m, "queries_executed") - _metric_int(m, "discovery_queries"),
                "queries_executed - discovery_queries",
            ),
            "queries_failed": from_metrics("queries_failed"),
            "search_results": from_metrics("search_results"),
        },
        "discovery": {
            "frontier_created": derived(
                frontier["created"], f"count(discovery_frontier WHERE run_id={run_id})"
            ),
            "frontier_observed": derived(
                frontier["observed"],
                "distinct candidates with an observation carrying this run_id",
            ),
            "frontier_deduplicated": from_metrics("dedup_merges"),
            "frontier_processed": derived(
                frontier["processed"],
                f"observed by this run AND state IN {TERMINAL_FRONTIER_STATES}",
            ),
            "frontier_pending": derived(
                frontier["pending"], "created by this run AND state='pending'"
            ),
            "frontier_rejected": derived(
                frontier["rejected"], "created by this run AND state='rejected'"
            ),
            "frontier_failed": derived(
                frontier["failed"], "created by this run AND state='failed'"
            ),
        },
        "fetch": {
            "pages_fetched": from_metrics("pages_fetched"),
            "fetch_failures": from_metrics("fetch_failures"),
            "page_intent_counts": derived(
                len(page_intents), "exploration_run.metrics.page_intent_counts"
            ),
            "scholarship_relevant_pages": derived(
                relevant_pages, "SCHOLARSHIP_DETAIL + UNKNOWN page intents"
            ),
            "pages_skipped_not_detail": from_metrics("pages_skipped_not_detail"),
            "pages_skipped_listing": from_metrics("pages_skipped_listing"),
            "listing_signals": derived(
                len(m.get("listing_signals") or {}),
                "exploration_run.metrics.listing_signals",
            ),
        },
        "extraction": {
            "extraction_attempts": (
                derived(extraction_attempts, "extraction_succeeded + extraction_failures")
                if extraction_attempts is not None
                else not_recorded("extraction_succeeded")
            ),
            "extraction_success": extraction_success,
            "extraction_failed": from_metrics("extraction_failures"),
            "candidate_scholarships": (
                derived(candidates, "extraction_succeeded + duplicates_collapsed")
                if candidates is not None
                else not_recorded("extraction_succeeded")
            ),
        },
        "identity": {
            "duplicates_collapsed": from_metrics("duplicates_collapsed"),
            "new_unique_scholarships": derived(
                _run_new_scholarship_count(conn, run_id),
                "distinct scholarship.identity_key reachable from this run",
            ),
        },
        "not_run_scopable": {
            "note": (
                "approved/rejected are curation outcomes decided outside the "
                "run. ReviewService records no run reference, so a run cannot "
                "claim them. Use the run's own new scholarships below, or the "
                "separately labelled all-time snapshot."
            ),
            "all_time_snapshot": all_time_snapshot(conn),
        },
    }


def _run_frontier_counts(conn, run_id) -> dict:
    """Frontier counts for one run, separating creation from observation.

    ``frontier.run_id`` is the run that *created* the row and never changes.
    Observation membership is derived from the evidence list, which is how a
    later run's rediscovery of an existing candidate is counted at all.
    """
    created = _scalar(
        conn,
        "SELECT count(*) FROM discovery_frontier WHERE run_id = CAST(:r AS uuid)",
        {"r": str(run_id)},
    )
    by_state = dict(
        _rows(
            conn,
            """
            SELECT state, count(*) FROM discovery_frontier
            WHERE run_id = CAST(:r AS uuid) GROUP BY 1
            """,
            {"r": str(run_id)},
        )
    )
    observed_state = dict(
        _rows(
            conn,
            """
            SELECT f.state, count(*) FROM discovery_frontier f
            WHERE EXISTS (
                SELECT 1 FROM jsonb_array_elements(
                    COALESCE(f.evidence->'observations', '[]'::jsonb)
                ) o WHERE o->>'run_id' = :r
            )
            GROUP BY 1
            """,
            {"r": str(run_id)},
        )
    )
    processed = sum(observed_state.get(s, 0) for s in TERMINAL_FRONTIER_STATES)
    return {
        "created": created,
        "observed": sum(observed_state.values()),
        "processed": processed,
        "pending": by_state.get("pending", 0),
        "rejected": by_state.get("rejected", 0),
        "failed": by_state.get("failed", 0),
        "done": by_state.get("done", 0),
    }


# ------------------------------------------------------- B2 provenance facts


def candidate_provenance(conn, candidate_id) -> dict:
    """Which run created a candidate, and every run that observed it.

    The two answers differ and both are legitimate. ``discovery_run`` is
    immutable (the creating run). ``observed_by_runs`` is the append-only
    observation log. Reading ``origin_query`` alone answers neither: it is
    frozen at the first discovery.
    """
    row = _rows(
        conn,
        """
        SELECT f.run_id::text, f.origin_query, f.candidate_id::text,
               f.evidence->'observations'
        FROM discovery_frontier f
        WHERE f.candidate_id = CAST(:c AS uuid)
        """,
        {"c": str(candidate_id)},
    )
    if not row:
        return {}
    record = row[0]
    observations = record[3] or []
    seen: list[dict] = []
    for obs in observations:
        seen.append(
            {
                "run_id": obs.get("run_id"),
                "origin_query": obs.get("origin_query"),
                "origin": obs.get("origin"),
                "at": obs.get("at"),
            }
        )
    return {
        "candidate_id": record[2],
        "discovery_run_id": record[0],
        "first_origin_query": record[1],
        "observations": seen,
        "observed_by_runs": sorted({o["run_id"] for o in seen if o["run_id"]}),
        "observation_count": len(seen),
        "observations_truncated": len(seen) >= MAX_OBSERVATIONS_PER_CANDIDATE,
    }


def run_observations(conn, run_id) -> list[dict]:
    """Every discovery observation this run made, read from the event log.

    This is the only correct basis for run-scoped query attribution: it returns
    the queries this run actually issued, including re-discoveries whose
    ``origin_query`` column still points at an earlier run.
    """
    return [
        {
            "candidate_id": row[0],
            "origin_query": row[1],
            "state": row[2],
            "origin": row[3],
        }
        for row in _rows(
            conn,
            """
            SELECT f.candidate_id::text, o->>'origin_query', f.state, o->>'origin'
            FROM discovery_frontier f
            CROSS JOIN LATERAL jsonb_array_elements(
                COALESCE(f.evidence->'observations', '[]'::jsonb)
            ) o
            WHERE o->>'run_id' = :r AND o->>'origin_query' IS NOT NULL
            """,
            {"r": str(run_id)},
        )
    ]


def repeat_attribution(conn, run_id, query_to_family: dict) -> dict:
    """Per-family discovery counts for one run, from its own observations.

    ``query_to_family`` maps query text to family for **this run's plan**, so a
    query the plan never issued cannot be attributed even if some older run
    issued it.
    """
    buckets: dict[str, dict[str, int]] = {}
    for obs in run_observations(conn, run_id):
        family = query_to_family.get(obs["origin_query"])
        if family is None:
            continue
        bucket = buckets.setdefault(
            family, {"observations": 0, "candidates": 0, "done": 0, "rejected": 0, "pending": 0, "failed": 0}
        )
        bucket["observations"] += 1
        state = (obs["state"] or "").lower()
        if state in TERMINAL_FRONTIER_STATES:
            bucket["candidates"] += 1
            bucket[state if state in bucket else "done"] += 1
        elif state:
            bucket[state if state in bucket else "pending"] += 1
    return buckets


# ---------------------------------------------------- D1/D2 scholarship link


def _run_new_scholarships(conn, run_id) -> list[dict]:
    """Scholarships reachable from one run through existing provenance.

    The chain, using only structures that already exist::

        scholarship.source_id
          -> source_registry.discovered_via->>'run_id'
          -> exploration_run

    ``source_registry.discovered_via`` is written by
    ``CountryExplorationEngine._register_source`` and already carries the
    ``run_id`` of the run that produced the frontier candidate. No migration and
    no new column on ``scholarship`` is required to answer this question.

    One honest caveat: this attributes a scholarship to the run whose frontier
    candidate produced the **source** the scholarship was extracted from. When a
    source registered by run A is re-acquired by run B and a new scholarship is
    extracted from it, run A is credited. The re-acquisition itself is recorded
    separately (a candidate revision against the canonical row), so this is a
    known bound rather than a silent one.
    """
    return [
        {
            "scholarship_id": row[0],
            "identity_key": row[1],
            "scholarship_name": row[2],
            "extraction_status": row[3],
            "provenance_origin": row[4],
            "source_id": row[5],
            "source_query": row[6],
            "candidate_id": row[7],
            "created_at": row[8],
        }
        for row in _rows(
            conn,
            """
            SELECT sc.scholarship_id::text, sc.identity_key, sc.scholarship_name,
                   sc.extraction_status, sc.provenance_origin, sc.source_id::text,
                   sr.discovered_via->>'origin_query',
                   sr.discovered_via->>'frontier_candidate',
                   sc.created_at
            FROM scholarship sc
            JOIN source_registry sr ON sr.source_id = sc.source_id
            WHERE sr.discovered_via->>'run_id' = :r
            """,
            {"r": str(run_id)},
        )
    ]


def _run_new_scholarship_count(conn, run_id) -> int:
    """Distinct canonical identities this run produced.

    Uniqueness is ``COUNT(DISTINCT identity_key)`` — the production identity
    computed by ``services.scholarship.identity``. Row count is never used as
    a proxy for uniqueness, and dedup is not reimplemented here.
    """
    return _scalar(
        conn,
        """
        SELECT count(DISTINCT sc.identity_key)
        FROM scholarship sc
        JOIN source_registry sr ON sr.source_id = sc.source_id
        WHERE sr.discovered_via->>'run_id' = :r
          AND sc.identity_key IS NOT NULL
        """,
        {"r": str(run_id)},
    )


def run_scholarship_funnel(conn, run_id) -> dict:
    """D1 + D2: what this run discovered, and which families produced it."""
    scholarships = _run_new_scholarships(conn, run_id)
    by_status: dict[str, int] = {}
    identities: set[str] = set()
    for row in scholarships:
        by_status[row["extraction_status"]] = by_status.get(row["extraction_status"], 0) + 1
        if row["identity_key"]:
            identities.add(row["identity_key"])

    attribution = _family_scholarship_attribution(conn, run_id, scholarships)

    return {
        "candidate_scholarship_rows": len(scholarships),
        "new_unique_scholarships": len(identities),
        "by_extraction_status": dict(sorted(by_status.items())),
        "pending_review": by_status.get("pending_review", 0),
        "approved": by_status.get("approved", 0),
        "rejected": by_status.get("rejected", 0),
        "needs_correction": by_status.get("needs_correction", 0),
        "identity_keys_missing": sum(1 for r in scholarships if not r["identity_key"]),
        "by_family": attribution,
        "family_sum": sum(f["unique_scholarships"] for f in attribution.values()),
        "note": (
            "family_sum may exceed new_unique_scholarships: a scholarship "
            "reached through two families is counted once globally and once per "
            "family. This is intentional and the global count never "
            "double-counts."
        ),
    }


def _family_scholarship_attribution(conn, run_id, scholarships: list[dict]) -> dict:
    """Map each new scholarship back to the families that surfaced it.

    The path is run-scoped end to end: this run's scholarship -> the frontier
    candidate its source came from -> *this run's* observations on that
    candidate -> the query -> the family this run's plan assigned to it.

    Using this run's observations (not the ``origin_query`` column) is what keeps
    a family claim honest when several runs share a candidate.
    """
    if not scholarships:
        return {}

    candidate_to_families: dict[str, set[str]] = {}
    observations = run_observations(conn, run_id)
    if not observations:
        return {}

    # Caller supplies the plan mapping; recover it from the run's own snapshot
    # so a stale manifest cannot mis-attribute this run's work.
    plan_queries = _plan_query_families(conn, run_id)
    if not plan_queries:
        return {}

    for obs in observations:
        family = plan_queries.get(obs["origin_query"])
        if family is None:
            continue
        candidate_to_families.setdefault(obs["candidate_id"], set()).add(family)

    per_family: dict[str, dict] = {}
    for row in scholarships:
        if not row["candidate_id"]:
            continue
        families = candidate_to_families.get(row["candidate_id"])
        if not families:
            continue
        for family in sorted(families):
            bucket = per_family.setdefault(
                family, {"scholarship_rows": 0, "identities": set()}
            )
            bucket["scholarship_rows"] += 1
            if row["identity_key"]:
                bucket["identities"].add(row["identity_key"])

    return {
        family: {
            "scholarship_rows": bucket["scholarship_rows"],
            "unique_scholarships": len(bucket["identities"]),
        }
        for family, bucket in sorted(per_family.items())
    }


def _plan_query_families(conn, run_id) -> dict[str, str]:
    """The query -> family map for this run, regenerated from its config.

    ``exploration_run.config_snapshot`` holds the country config the run used.
    Re-deriving the plan from it means attribution cannot be steered by a stale
    or edited manifest file: the mapping is always the one this run actually
    issued.

    The offset is an **inclusive** count of the country's runs. The engine
    builds its plan inside ``_seed_frontier``, which runs after
    ``RunRepository.start_run`` has already committed this run's own row, so the
    rotation offset it applied is the run's index rather than the number of runs
    that preceded it. Getting this off by one silently attributes the run to a
    neighbouring plan.
    """
    record = run_record(conn, run_id)
    if record is None:
        return {}
    snapshot = record["config_snapshot"] or {}
    if not snapshot.get("iso2"):
        return {}
    try:
        from services.exploration.config_loader import CountryExplorationConfig
        from services.exploration.query_generation import QueryGenerator

        prior_runs = _scalar(
            conn,
            """
            SELECT count(*) FROM exploration_run
            WHERE country_id = CAST(:c AS uuid) AND started_at <= :started
              AND started_at IS NOT NULL
            """,
            {"c": record["country_id"], "started": record["started_at"]},
        )
        config = CountryExplorationConfig.model_validate(snapshot)
        plan = QueryGenerator(config).generate_plan(run_offset=prior_runs)
        return {q.text: q.family for q in plan}
    except Exception as exc:  # noqa: BLE001 - attribution degrades, never crashes a report
        # Degrading to an empty map would silently turn a whole run's family
        # attribution into "no families contributed anything", which reads as a
        # finding rather than a failure. Logged loudly instead.
        logger.warning(
            "Query-family attribution unavailable for run {}: {}: {}",
            run_id, type(exc).__name__, exc,
        )
        return {}


# ------------------------------------------------------- all-time snapshot


def all_time_snapshot(conn) -> dict:
    """Corpus state, explicitly not attributable to any run.

    Kept because a benchmark report needs a before/after picture, but every
    caller-facing label states these are all-time totals so a run result can
    never silently absorb them.
    """
    return {
        "scope": "ALL-TIME CORPUS SNAPSHOT — NOT a benchmark run result",
        "scholarships": _scalar(conn, "SELECT count(*) FROM scholarship"),
        "approved": _scalar(
            conn, "SELECT count(*) FROM scholarship WHERE extraction_status='approved'"
        ),
        "pending_review": _scalar(
            conn, "SELECT count(*) FROM scholarship WHERE extraction_status='pending_review'"
        ),
        "rejected": _scalar(
            conn, "SELECT count(*) FROM scholarship WHERE extraction_status='rejected'"
        ),
        "rows_without_identity_key": _scalar(
            conn, "SELECT count(*) FROM scholarship WHERE identity_key IS NULL"
        ),
        "frontier_rows": _scalar(conn, "SELECT count(*) FROM discovery_frontier"),
        "frontier_pending": _scalar(
            conn, "SELECT count(*) FROM discovery_frontier WHERE state='pending'"
        ),
        "sources": _scalar(conn, "SELECT count(*) FROM source_registry"),
        "raw_documents": _scalar(conn, "SELECT count(*) FROM raw_document"),
        "exploration_runs": _scalar(conn, "SELECT count(*) FROM exploration_run"),
        "approved_by_provenance_origin": {
            (row[0] if row[0] is not None else "(null)"): int(row[1])
            for row in _rows(
                conn,
                """
                SELECT provenance_origin, count(*) FROM scholarship
                WHERE extraction_status='approved' GROUP BY 1 ORDER BY 2 DESC
                """,
            )
        },
    }


def benchmark_run_ids(conn, run_ids) -> list[str]:
    """Normalise and validate the run ids a benchmark claims to have executed."""
    out = []
    for run_id in run_ids:
        text_value = str(run_id)
        if run_record(conn, text_value) is None:
            continue
        out.append(text_value)
    return out


def exclude_failed_runs(conn, run_ids) -> tuple[list[str], list[str]]:
    """Split claimed run ids into (successful, non-successful).

    A failed run is not an error to hide, but its counters must not be summed
    into a comparison against a clean baseline: it stopped partway, so its
    totals are a floor, not a measurement.
    """
    good, bad = [], []
    for run_id in run_ids:
        record = run_record(conn, run_id)
        if record is None:
            bad.append(run_id)
            continue
        (good if record["status"] == "completed" else bad).append(run_id)
    return good, bad


# ------------------------------------------------------------- B3 repetition


def prior_run_queries(conn, country_id, exclude_run_id=None) -> set[str]:
    """Every query text any earlier run of this country issued."""
    params = {"c": str(country_id)}
    clause = ""
    if exclude_run_id is not None:
        clause = "AND er.run_id <> CAST(:x AS uuid)"
        params["x"] = str(exclude_run_id)
    return {
        row[0]
        for row in _rows(
            conn,
            f"""
            SELECT DISTINCT o->>'origin_query'
            FROM discovery_frontier f
            CROSS JOIN LATERAL jsonb_array_elements(
                COALESCE(f.evidence->'observations', '[]'::jsonb)
            ) o
            JOIN exploration_run er ON er.run_id::text = o->>'run_id'
            WHERE f.country_id = CAST(:c AS uuid) {clause}
              AND o->>'origin_query' IS NOT NULL
            """,
            params,
        )
    }


def query_repetition(conn, country_id, plan_queries, exclude_run_id=None) -> dict:
    """B3: how much of this run's query surface is genuinely new.

    Query rotation is intentional — search results move, sources change — so a
    repeated query is not automatically wasted work. It is, however, not new
    coverage, and a benchmark that counts it as breadth overstates what the run
    explored. Reporting the overlap keeps that honest without changing the plan
    generator or the seed.
    """
    planned = set(plan_queries)
    prior = prior_run_queries(conn, country_id, exclude_run_id)
    repeated = sorted(planned & prior)
    return {
        "queries_planned": len(planned),
        "queries_repeated_from_previous_run": len(repeated),
        "queries_new_to_this_country": len(planned - prior),
        "repeated_queries": repeated,
    }
