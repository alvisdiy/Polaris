# Benchmark Harness Audit

**Status:** NOT READY
**Date:** 2026-10-05
**Scope:** Measurement trustworthiness of the Scholarship Discovery Benchmark only.
**Phase:** V0.1.3 benchmark readiness. No live discovery, no Serper, no schema migration.

---

## Original Audit

The first benchmark harness was not trustworthy. Four independent defects were
found, each sufficient on its own to make a reported number wrong.

State at the time of the audit: **15 exploration runs** (10 completed,
4 failed, 1 orphaned `running`), 6,796 frontier rows, 206 scholarships, 40
approved, `identity_key` NULL 0.

**1. The funnel was entirely database-wide.**
`_funnel()` defined 17 metrics. All 17 read the whole corpus. Not one was
scoped to the run being measured. `approved` read
`count(*) FROM scholarship WHERE extraction_status='approved'` and would have
reported 40 as a discovery result, when only 9 of those 40 records were
produced by the engine at all:

```
approved by provenance_origin: unknown 18, phase3_acquisition 13, exploration 9
```

**2. Query attribution read a frozen column.**
`FrontierRepository.upsert_candidate` keys on `UNIQUE(country_id, url_hash)`.
When a later run rediscovers an existing candidate it appends to
`evidence.observations` and leaves `run_id` and `origin_query` untouched. The
column therefore answers "which query found this URL *first*", never "which
query found it in *this* run". Attribution read exactly that column.

Measured on the live corpus:

```
1666  frontier rows carry more than one observation
 924  frontier rows were observed by more than one distinct run_id
 227  frontier rows where the origin_query column differs from the newest observation
```

**3. The recorded query plan was not the plan that ran.**
`CountryExplorationEngine.run()` calls `RunRepository.start_run()`, which
**commits its own row**, and only then calls `_seed_frontier()`, which computes
`prior_runs = count(ExplorationRun WHERE country_id)`. That count includes the
run being started, so the engine rotates to `run_offset = prior + 1`.

The harness called `_plan_signature()` *before* the run existed and recorded
`generate_plan(prior)`. The manifest therefore described a neighbouring plan.
Measured against the 2026-10-04 batch:

```
country  executed  resolvable via manifest  unattributable
KR              12                    4                8  (33%)
ID              12                    1               11  ( 8%)
GB              12                    0               12  ( 0%)
SG              12                    0               12  ( 0%)
TOTAL           48                    5               43  (90%)
```

90% of executed queries had no family mapping at all. This, not a missing
filter, is why the earlier attribution pass reported GB = 0 and ID = 2.

**4. A numerator was missing entirely.**
`AcquisitionMetrics` produced `extraction_succeeded`, but only
`extraction_failures` was copied into `ExplorationMetrics`, so
`exploration_run.metrics` carried no extraction numerator and every funnel
printed NOT MEASURABLE for it.

**Baseline.** `~26.0 queries / approved scholarship = 1039 / 40`. Retained
here only as `HISTORICAL CONTAMINATED REFERENCE`:

- the denominator 40 contains 18 records that predate the engine
  entirely (`provenance_origin='unknown'`); engine-produced approved is 9
- the numerator 1039 is `queries_executed`, which counts authority-resolution
  queries. `discovery_queries` is 12 per run.
- the neighbouring figure "5.1 queries per persisted scholarship" is
  `1039 / 202` (all-time row count), not `1039 / 135` (engine-persisted) as
  its label implies.

`BASELINE PROVENANCE: PARTIALLY VERIFIABLE`. The formula reconstructs, but
neither side of the ratio is a clean engine measurement.

**Invalid batch 1.** `docs/progress/benchmark_runs_batch1_invalid.json` records
4 runs from 2026-10-04. All four are still in the database and all four are
`status='failed'`:

```
run_id       status   queries  frontier rows
bb7869ff     failed        64             166
9e54c6fd     failed       148             309
5036e90a     failed       194             719
6a17ae93     failed       156             372
8691b294     running       -             470   <- orphaned, finished_at NULL
```

```
Historical invalid runs:            4 failed + 1 orphaned, dated 2026-10-04
Database state contamination:       frontier 4760 -> 6796 (+2036)
                                    scholarships 202 -> 206 (+4)
                                    approved 40 -> 40 (boundary held)
Current benchmark metric contamination: Σ queries_executed 1039 -> 1601 (+562)
Safe to use as baseline:             NO. Historical diagnostic only.
```

`8691b294` is a killed process: `status='running'`, `finished_at` NULL, 470
frontier rows already written. `RunRepository.fail_stale_running` will close it
at the start of the next run for that country, but until then it is counted as
an unfinished run.

---

## Corrections

Errors made by this audit while implementing the fixes, recorded because each
one had produced a stated finding:

- **`_funnel()` has 17 entries, not 16**, and **0** of them were run-scoped.
  An intermediate message said "12 of 16 database-wide". The correct figure is
  17 of 17, which is worse than first reported.
- **Query-repetition was measured wrong at first.** The first pass reused one
  `QueryGenerator` across all offsets. That instance's RNG advances between
  calls, so it does not model separate runs. `CountryExplorationEngine.__init__`
  builds a fresh generator per run. Re-measured with a fresh generator per
  offset, repetition is still real but the specific queries differ.
- **The run-offset off-by-one was missed** during the first audit pass and only
  surfaced when the D2 test failed with `KeyError: 'funding'`.

---

## B1 Run-Scoped Funnel

Implemented in `services/exploration/benchmark_metrics.py`.

Metrics are taken from the source that is authoritative for them, never
subtracted from corpus totals:

| Group | Source |
|---|---|
| `queries_executed`, `discovery_queries`, `queries_failed`, `search_results`, `pages_fetched`, `fetch_failures`, `pages_skipped_*`, `listing_signals`, `dedup_merges`, `duplicates_collapsed`, `extraction_failures` | `exploration_run.metrics` (written at run finalise) |
| `queries_authority` | derived: `queries_executed - discovery_queries` |
| `frontier_created` | `count(*) WHERE run_id = :run_id` |
| `frontier_observed` | distinct candidates with an observation carrying `run_id` |
| `frontier_processed` | observed by this run AND state in `(done, rejected, failed)` |
| `frontier_pending` / `rejected` / `failed` | created by this run AND that state |
| `scholarship_relevant_pages` | `SCHOLARSHIP_DETAIL + UNKNOWN` intents |
| `extraction_attempts` / `candidate_scholarships` | derived when `extraction_succeeded` exists |

`frontier_created` and `frontier_observed` are reported separately on purpose.
Creation is the run's `run_id` column; observation comes from the evidence
list. Measured on a real run: created 312, observed 437, so 125 candidates
were rediscoveries that a creation-only metric would have hidden.

Every metric carries `source`, `value` and `recorded`. A metric the run never
persisted reports `value=None, recorded=False` rather than 0. Verified on the
September runs: `extraction_success` correctly reports "not recorded" because
the counter did not exist then.

All-time totals are now confined to `all_time_snapshot()`, whose `scope` field
reads `ALL-TIME CORPUS SNAPSHOT - NOT a benchmark run result`.

## B2 Provenance Integrity

No schema change and no new column were needed. The frontier observation list
is already an append-only event log with a `run_id` on each entry.

```sql
SELECT f.candidate_id::text, o->>'origin_query', f.state, o->>'origin'
FROM discovery_frontier f
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(f.evidence->'observations', '[]'::jsonb)
) o
WHERE o->>'run_id' = :run_id AND o->>'origin_query' IS NOT NULL
```

`candidate_provenance()` returns both facts separately: `discovery_run_id`
(immutable, the creating run) and `observed_by_runs` (from the event log).

One bound, documented rather than hidden: `FrontierRepository._merge_observation`
keeps the most recent 20 observations per candidate. A URL discovered more than
20 times has its oldest observations truncated, so attribution is exact for
recent runs rather than for all of history.

## B3 Query Rotation

The rotation mechanism is functioning as designed; the problem was that the
benchmark could not tell an intentional revisit from an accidental repeat.

Re-measured with a fresh generator per offset, over 10 configured countries and
offsets 0-9:

```
country  distinct  reused  worst repeat
FR            62       31            10   'France aide financiere ...' at all 10 offsets
JP            65       31             7   localized family
KR            59       32             7   localized family
DE            65       33             6
SG            70       30             6
CN            66       32             5
AU            65       32             5
GB            75       32             4
ID            75       35             4
US            74       35             4
```

The concentration is structural, not a bug: `localized` has exactly one
template and a small native-script vocabulary pack, so it can only render a
handful of distinct queries. The rotation cursor and template index both move;
the vocabulary does not.

Repeated queries are legitimate, since search results move and source coverage
changes. They are also not new coverage. Rather than change the plan generator,
`query_repetition()` measures the overlap and the harness prints it:

```
KR: 12 planned, 7 repeated from a prior run, 5 new to this country
```

The generator is unchanged: deterministic, sha256-seeded, no OS entropy, no
`hash()`, bounded by `max_queries_per_run`, no Cartesian expansion.

## D1 Scholarship -> Run

Attribution uses structures that already existed. No foreign key was added to
`scholarship`.

```
scholarship.source_id
  -> source_registry.discovered_via->>'run_id'
  -> exploration_run
```

`discovered_via` is written by `CountryExplorationEngine._register_source` and
already carries `run_id`, `origin_query` and `frontier_candidate`. Verified live:
all 27 `provenance_origin='exploration'` scholarships resolve to a source row
and to a run; 338 of 396 sources carry `discovered_via.run_id`.

Documented bound: this credits the run whose frontier candidate produced the
**source** the scholarship was extracted from. When a source registered by run
A is re-acquired by run B and yields a new scholarship, run A is credited. The
re-acquisition is separately recorded as a candidate revision against the
canonical row, so the bound is visible rather than silent.

## D2 Query Family -> Scholarship

```sql
global:   COUNT(DISTINCT identity_key)
per-family: COUNT(DISTINCT identity_key) GROUP BY query_family
```

The global count never double-counts. A scholarship reached through two
families is one global unique and one per family, so the family sum may exceed
the global total. That is intentional and asserted by test.

The chain is run-scoped end to end: this run's scholarship, to the frontier
candidate its source came from, to *this run's* observations on that candidate,
to the query, to the family in this run's plan.

The query-to-family map is regenerated from `exploration_run.config_snapshot`
using an **inclusive** run count, matching what the engine did. It is not read
from the manifest, so a stale or edited manifest cannot steer attribution.

The canonical identity algorithm is untouched, and dedup is not reimplemented.
The database enforces uniqueness itself: the partial unique index
`uq_scholarship_identity` rejects a second row under one identity_key, which
is a stronger guarantee than a counter behaving correctly.

**Family attribution is a lower bound.** Only scholarships whose source traces
to a candidate observed by one of this run's queries are attributed. Measured:

```
run 3f8d6569: 42 rows, 42 unique, families attributed 36 (opportunity 18,
              official_source 16, provider 2)
run 413eea21: 48 rows, 48 unique, families attributed 12 (official_source)
```

The un-attributed remainder comes from sources registered via seed or
known-source enqueue, which carry no `origin_query`. This is reported as a
lower bound, never as "these families produced nothing".

---

## Historical Baseline

`~26.0 queries / approved scholarship` is retained as
`HISTORICAL CONTAMINATED REFERENCE` only. It is not a clean engine-efficiency
baseline and must not be the comparison target for a new run.

The new harness must establish its own baseline from engine-produced records
under the corrected plan. Until such a run exists, there is no authoritative
comparison figure, and the verdict for the 7-family expansion cannot be reached.

## Invalid Batch Assessment

`docs/progress/benchmark_runs_batch1_invalid.json` is retained as evidence and
not used as a baseline.

- **Why invalid:** all four runs are `status='failed'`; the yield was 0, 0, 3, 1
  persisted scholarships; `page_intent_counts` is empty despite acquisition
  having run.
- **What it proves:** a 7-family plan executes end to end through the production
  engine, the frontier accepts 300-700 candidates per run, and source
  registration and verification work at volume.
- **What it does not prove:** any yield, approval, duplicate-rate or family
  conclusion. Its recorded plan was also off by one, so its family attribution
  is unusable by construction.
- **Rows remaining:** yes. 1,566 frontier rows and 4 scholarship rows from those
  four runs are still live. They are excluded from run-scoped reporting by
  construction, because a run-scoped metric filters on `run_id` and status.
- **Its metrics still contaminate:** any corpus-wide aggregate, including
  `Σ metrics.queries_executed`, now reads 1601 rather than the 1039 the 26.0
  figure was derived from.

## Changes Implemented

| File | Change |
|---|---|
| `services/exploration/benchmark_metrics.py` | New. Run-scoped funnel, observation-based provenance, scholarship and family attribution, query repetition, run accounting, labelled corpus snapshot. |
| `scripts/v013_discovery_benchmark.py` | Rewritten to consume run-scoped measurements. Records `run_id` and `run_status` in the manifest. Records the plan the engine actually executes. Prints the contaminated reference as a labelled reference. `sys.path` bootstrap added so the script is directly runnable. |
| `services/exploration/engine.py` | `ExplorationMetrics.extraction_succeeded` added and accumulated from the same call site as `extraction_failures`. One pre-existing E501 wrapped. |
| `tests/integration/test_benchmark_metrics.py` | New. 20 tests. |

No migration. No change to the identity algorithm, dedup, page intent, listing
guard, thresholds, crawl depth, frontier budget or query templates.

## Tests

```
pytest                                   1511 passed, 6 skipped, 0 failed
ruff check (changed files)               All checks passed
coverage services.exploration.benchmark_metrics   86% (174 stmts, 24 missed)
```

Baseline before this work was 1491 passed, 6 skipped. The 20 new tests:

- **B1** two runs report 3 and 5 candidates independently, never 8 and 8;
  authority queries derived as a difference; every funnel entry declares its
  source; corpus snapshot is labelled and held apart from run results.
- **B1/extraction** a counter the run never recorded reports `None`, not `0`;
  a recorded counter produces attempts and candidates.
- **B2** a shared frontier row keeps both runs' observations; the
  `origin_query` column stays frozen at first discovery; family attribution
  for run A never sees run B's query.
- **B3** repeated queries are disclosed as repeats, fresh queries as new; the
  plan is deterministic per offset and rotation moves it.
- **D1** a new scholarship is credited to its run and not to a later one;
  `uq_scholarship_identity` rejects a repeated identity.
- **D2** one scholarship via two families yields global 1, funding 1, ecosystem
  1, family sum 2; legacy `provenance_origin='unknown'` rows are never counted.
- **Approval** a record approved before a run is not `approved` for that run;
  an unknown run id is reported, not silently dropped.
- **Accounting** failed runs are separated from completed and never summed.

## Coverage

```
services/exploration/benchmark_metrics.py   174 stmts   24 missed   86%
```

The uncovered lines are the degraded-failure branches: the error handler in
`_plan_query_families`, the `observed_by_runs` collapse, and the
`exclude_failed_runs` unknown-id path beyond what the tests already assert.

This is measured against the full suite, not the benchmark tests alone, so it
reflects the module's real coverage rather than coverage manufactured by
importing it in one test file.

## Database Integrity

Unchanged by this work. No writes were issued outside the rollback-isolated
test transaction.

```
scholarships                206   unchanged
approved                     40   unchanged
identity_key NULL             0   invariant holds
pending_review                8
exploration_runs             15   unchanged (10 completed, 5 not completed)
frontier                   6796   unchanged
sources                     396
raw_documents               405
alembic head        a4c7e91b2d05   unchanged, no migration added
```

## Remaining Limitations

1. **No clean baseline exists.** The only reference figure is contaminated. The
   first live run under the corrected harness must establish a baseline rather
   than attempt a comparison.
2. **Family attribution is a lower bound.** Scholarships reached from sources
   registered by seed or known-source enqueue carry no `origin_query` and are
   not attributed to any family.
3. **The D1 chain credits the source's run, not the extracting run.** Cross-run
   re-acquisition credits the earlier run.
4. **Observation history is bounded to 20 per candidate.** Attribution is exact
   for recent runs, not for all history.
5. **`approved` is a snapshot, not an attribution.** `ReviewService` records no
   run reference, so approval is a delayed quality metric measured against the
   run's own new records.
6. **Five runs are not completed**, including one orphaned `running` row with
   470 frontier rows. They are excluded from run-scoped reporting but still sit
   in the frontier and will be re-enqueued by the next run for that country.
7. **The corrected harness has never been exercised against a live run.** All
   verification here is against historical runs and offline tests.

## Final Readiness

The seven questions the benchmark must answer:

| Question | Answerable |
|---|---|
| What did this run discover? | Yes, run-scoped |
| How many unique scholarships did it discover? | Yes, `COUNT(DISTINCT identity_key)` |
| Which query families contributed them? | Partially, lower bound, remainder disclosed |
| How many were duplicates? | Yes, `duplicates_collapsed` from the run |
| How many entered review? | Yes, `pending_review` of the run's own records |
| How many were subsequently approved? | Partially, snapshot not attribution |
| How does this compare to the historical baseline? | No, no clean baseline exists |

```
BENCHMARK STATUS:
NOT READY
```

**BLOCKER 1: No clean baseline exists under the corrected harness.**
The 26.0 reference is contaminated on both sides, and the five non-completed
October runs have already moved the corpus aggregate from 1039 to 1601. The
first live run must establish a baseline from engine-produced records. Running
a comparison run first would produce a number with nothing trustworthy to
compare against.

**BLOCKER 2 (RESOLVED): Family attribution is a lower bound.**
36 of 42 rows were attributed for run `3f8d6569`; 12 of 48 for run `413eea21`.
Reporting the unattributed remainder was part of this work:
`_family_report()` now prints `NOT ATTRIBUTED TO ANY FAMILY: N of M row(s)`
with the reason, so a partial family table cannot be read as "these families
produced nothing". The bound itself remains and is a property of the data, not
a defect to fix: a scholarship whose source was registered by seed or
known-source enqueue carries no `origin_query`.

**MINIMUM FIX:**
Blocker 1 needs no code, only sequencing: establish a baseline run before any
comparison run. Neither blocker requires a migration, a schema change, or a
change to the discovery engine.