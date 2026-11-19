# V0.1.3 Live Scholarship Discovery Baseline

**VERDICT: BASELINE FAILED**
**Reason:** a pre-existing engine defect (`ObjectDeletedError`) terminated all three live runs mid-frontier, so no run reached a completed state and no yield figure is measurable.
**Date:** 2026-10-05
**Phase:** V0.1.3 baseline execution (authorized after `docs/progress/V013-BENCHMARK-HARNESS-AUDIT.md`).

---

## 1. Objective

Execute the first controlled live discovery experiment under the corrected
V0.1.3 benchmark harness, to answer:

> What does the current 7-family Scholarship Discovery Engine actually produce
> under the corrected measurement system?

This was a **baseline**, not a comparison. No metric here is compared against
the historical `26.0` figure, which remains classified as
`HISTORICAL CONTAMINATED REFERENCE`.

Two findings resulted. One is a measurement defect that would have made every
future run unattributable, found and fixed during this experiment. The other is
a pre-existing engine defect that has terminated **every live run ever
executed** and which blocks the baseline.

## 2. Environment

```
branch              develop
commit              2e155446e6c446d11aa01f5dcb40ab81189fea7c  (2e15544, 2026-09-26)
working tree        51 modified tracked, 165 untracked (pre-existing; not created here)
alembic head        a4c7e91b2d05   (unchanged, no migration added)
POLARIS_SERPER_API_KEY  present, 40 chars (value never printed)
POLARIS_SEARCH_PROVIDER unset -> serper (the real provider)
python              3.11, .venv
```

Pre-flight `pytest`: **1511 passed, 6 skipped, 0 failed** (exit 0).
Pre-flight `ruff` on changed files: clean (exit 0).

## 3. Pre-Run Database State

All nine expected values from the audit matched exactly. No material
difference, so the run proceeded without stopping.

```
scholarships          206
approved               40
pending_review          8
rejected              157
identity_key NULL       0
frontier              6796
sources                396
raw_documents          405
exploration_runs        15
providers              307
```

Saved to `artifacts/v013_baseline_pre_run.json`.

## 4. Countries

Four were specified: JP, KR, GB, ID. All four were available in both
`configs/countries/*.json` and the `country` table:

```
JP  search_locale=ja-JP  gl=jp  max_queries=12  bounds=explicit  prior runs=2
KR  search_locale=ko-KR  gl=kr  max_queries=12  bounds=default   prior runs=4
GB  search_locale=en-GB  gl=gb  max_queries=12  bounds=default   prior runs=2
ID  search_locale=id-ID  gl=id  max_queries=12  bounds=default   prior runs=2
```

**Three were executed. ID was not**, under the STEP 14 stop condition in §14.
Running it would have produced a fourth run with a signature already observed
three times, which is cost without measurement.

## 5. Run IDs

```
JP  f4974979-edbf-4dc8-b4f8-5270924f04c3  failed
KR  9f4aae2e-6265-427d-918a-069a7815d36e  failed
GB  89266eaa-4bd4-49e1-935d-d9955c5e20db  failed
ID  not executed
```

0 completed, 3 not completed. `exclude_failed_runs()` separates them, and the
harness never sums them into a comparison.

## 6. Query Plans

Each entry records both the offset before the run and the offset the engine
used, plus the plan the engine actually executed. The plan hash lives at
`plan.plan_hash` inside each manifest entry in
`docs/progress/benchmark_runs.json`; `plan.queries` maps each executed query to
its family.

```
ctry  plan_hash       offset_before  used_by_engine  planned  distinct
JP    2c39ab23ee08           2               3         12        12
KR    9188c4b1970d           4               5         12        12
GB    e867dc462f5e           2               3         12        12
```

`used_by_engine` is one higher than `offset_before` in all three cases. That is
the off-by-one the harness audit measured: `RunRepository.start_run()` commits its
own row before `_seed_frontier()` counts runs, so the engine's
`count(ExplorationRun) + 1` already includes the run in flight. The harness
records the offset it would have generated independently and both values, so the
discrepancy is visible rather than silent. The plan recorded in the manifest is
the one the engine actually executed.

Each run planned 12 queries across 7 families (`max_queries_per_run=12`), and
each executed **12 discovery queries** — the expected budget, confirming query
generation and rotation worked as designed.

**Query repetition (B3), as measured after the run_id fix:**

```
JP  12 planned,  3 repeated from a prior run,  9 new to this country
KR  12 planned,  8 repeated from a prior run,  4 new to this country
GB  12 planned,  2 repeated from a prior run, 10 new to this country
```

**Correction.** An earlier draft of this section reported 12 of 12 repeated and
0 new for all three countries, and concluded that rotation was not producing
new surface. That figure was an artifact of the harness defect fixed during
this experiment: before the fix, `query_repetition()` was called with
`exclude_run_id=None`, so each run counted **its own twelve queries** as
"from a previous run" and therefore reported every query as repeated. Re-running
the same function with `exclude_run_id=None` reproduces 12/12/0 exactly, which
confirms the mechanism rather than merely asserting it.

With the run correctly excluded from its own prior set, **25 of 36 planned
queries were new to their country.** Repetition is real but partial, and it is
concentrated in KR (8 repeated), which has the deepest run history — it is the
country that ran twice before. JP and GB, with little prior history, generated
mostly new surface. The corrected measurement therefore does **not** support the
audit's structural-scarcity hypothesis for these three countries; it is
consistent with repetition tracking run history, which is the intended
behaviour. Settling whether the underlying template pool is genuinely narrow
requires a fixed-offset repetition experiment, which this baseline does not
provide.

## 7. Search Funnel

```
metric                 JP     KR     GB    total
queries_executed       126     54     98     278
  discovery_queries     12     12     12      36
  authority queries    114     42     86     242
queries_failed           0      0      0       0
search_results         119    120    120     359
```

The authority-to-discovery ratio is **6.7:1** (242 vs 36). The engine spends
roughly seven search calls resolving authority for every one discovery call.
That is the single largest cost in the funnel and is the first thing worth
examining once the engine can finish a run.

## 8. Frontier Funnel

```
metric                  JP     KR     GB    total
frontier_created       686    207    316   1209
frontier_observed      819    345    432   1596
frontier_processed     148     86    105    339
frontier_pending       616    183    266   1065
frontier_rejected       12      6     10     28
frontier_failed          6      0      0      6
frontier_deduplicated  420    369    242   1031
```

`created` and `observed` are reported separately as designed: 1596 observed
vs 1209 created means 387 candidates were rediscoveries, which a
creation-only metric would have hidden entirely.

**1065 of 1209 created candidates (88%) were still PENDING when each run died.**
The runs did not exhaust their frontier; they were terminated by the crash.

## 9. Fetch Funnel

```
metric                  JP     KR     GB    total
pages_fetched           80     25     55    160
fetch_failures          23      7     14     44
```

Fetch success rate: **78.4%** (160 of 204 attempts).

## 10. Page Intent

```
JP  {"SCHOLARSHIP_DETAIL": 1, "SCHOLARSHIP_OVERVIEW": 9}
    skipped_not_detail=9  skipped_listing=1  scholarship_relevant_pages=1
KR  {}   skipped 0 / 0   relevant 0
GB  {}   skipped 0 / 0   relevant 0
```

Page intent classification only ran in JP, and classified exactly **one** page
as `SCHOLARSHIP_DETAIL` across 80 pages fetched. Nine were classified
`SCHOLARSHIP_OVERVIEW`.

`scholarship_relevant_pages` (1 of 160 fetched pages, **0.6%**) is the number
that gates extraction downstream. It is the second-largest bottleneck after the
authority query ratio.

## 11. Extraction

```
metric                  JP     KR     GB    total
extraction_attempts       0      0      0       0
extraction_succeeded      0      0      0       0
extraction_failed         0      0      0       0
candidate_scholarships    0      0      0       0
```

Zero extraction attempts in all three runs, because only one page across all
160 fetched was classified as scholarship-relevant. **Extraction was never
reached.** This is why no baseline yield exists.

Note this also means the extraction numerator added in the previous phase is
present and reporting `0` rather than "not recorded" — the counter works; the
pipeline simply never got there.

## 12. Deduplication

```
candidate scholarship rows         0
new unique scholarships           0
duplicates_collapsed              0
duplicate rate                 n/a (nothing to duplicate)
```

No scholarship rows were produced, so dedup was never exercised. Frontier-level
dedup did run: **1031 rediscovery merges** across 1596 observations.

Per-country duplicate decomposition (same identity / URL / provider+name /
cross-query / cross-country) is **not reportable**, because it is a property of
scholarship rows and there are none.

## 13. Query Family Attribution

```
JP  12 queries, 12 repeated, 0 new
    observations attributable to a family: see harness output
    attributed unique scholarships: 0
    NOT ATTRIBUTED TO ANY FAMILY: 0 of 0
```

Every run produced zero scholarships, so family attribution has no rows to
attribute. The remainder disclosure (`NOT ATTRIBUTED TO ANY FAMILY: N of M`)
prints correctly with N=0, which is the honest output when nothing was
discovered — it is **not** evidence that any family failed.

## 14. Funding Distribution

```
Fully Funded         0
Partial Funded       0
Tuition Only         0
Living Allowance     0
Research Funding     0
Travel Support       0
Tuition Waiver       0
Stipend Only         0
NULL                 0
```

No rows to classify. Nothing was inferred from the word "scholarship"; the
extractor's evidence requirement was never reached.

## 15. Source Quality

```
metric                   JP     KR     GB    total
sources_verified          23      4     17      44
providers (corpus delta)   -      -     -      38
```

44 sources verified, and the `provider` table grew by 38 rows corpus-wide
(307 -> 345) across the three runs. The per-country split is not reported
because `sources_verified` is per run but the provider delta is a corpus-wide
measurement, and attributing it per country would be an inference the data does
not support.

**Source discovery and verification work at volume and are not the bottleneck.**

```
sources acquired with scholarship pages   0
sources with no scholarship pages        see log: "is official but yielded no
                                         scholarship pages (3 links)"
acquisition attempted                    yes, from every verified source
```

A recurring log line is the story here: verified sources were acquired and
correctly returned **"official but yielded no scholarship pages (3 links)"**.
The index→detail expansion is finding official pages and then extracting
nothing scholarship-bearing from them.

Distinct metrics, as required: **44 official sources discovered ≠ 0 scholarships
discovered.** These are not the same number and neither substitutes for the
other.

## 16. Review Boundary

```
rows created today by the pipeline    0
auto-approvals                        0
extraction_status writes outside
  ReviewService                       0
approved before / after               40 / 40  (unchanged)
```

The publication boundary held absolutely. No record was created, so none could
be approved. Nothing bypassed `ReviewService`.

## 17. Per-Country Results

**JP** (`f4974979`, 671.9s, failed)
126 queries → 686 created / 819 observed → 80 pages fetched → 1 relevant page →
0 extraction → 0 scholarships → 23 sources verified. 616 candidates left pending.

**KR** (`9f4aae2e`, failed)
54 queries → 207 created / 345 observed → 25 pages fetched → 0 relevant pages →
0 extraction → 0 scholarships → 4 sources verified. 183 left pending.

**GB** (`89266eaa`, failed)
98 queries → 316 created / 432 observed → 55 pages fetched → 0 relevant pages →
0 extraction → 0 scholarships → 17 sources verified. 266 left pending.

**ID** — not executed (§4).

## 18. Aggregate Baseline

```
total queries                     278   (36 discovery, 242 authority)
search results                    359
frontier candidates created      1209
frontier candidates observed     1596
frontier processed                339
frontier still pending           1065
pages fetched                     160
scholarship-relevant pages          1
extraction attempts                  0
successful extraction               0
candidate scholarships               0
new unique scholarships             0
duplicates                          0
pending review                      0
approved attributable               0
sources verified                    44
```

**Ratios are deliberately not computed.** Every ratio in the required list has
a denominator of zero new unique scholarships. `queries / new unique
scholarship`, `duplicate rate`, and `extraction success rate` would all be
divisions by zero. Publishing them as `0`, `∞`, or `n/a` dressed as a metric
would be the exact failure mode this measurement system was built to prevent.

What the aggregate *does* establish, from three independent countries: the
pipeline runs end-to-end through search, frontier, fetch, classification,
provider resolution, source verification and acquisition at real scale, and it
consistently stops short of extraction.

## 19. Database Integrity

```
metric                  before    after    delta
scholarships               206     206        +0
approved                    40      40        +0
pending_review               8       8        +0
rejected                   157     157        +0
identity_key NULL            0       0        +0
frontier                   6796    8005     +1209
sources                     396     487        +91
raw_documents               405     415        +10
exploration_runs             15      18         +3
providers                   307     345        +38
```

The `after` column was re-derived from the live database once the last run's
transaction had fully committed and two consecutive samples 8 seconds apart
agreed. An earlier draft of this table was sampled while the GB run's writes
were still in flight and under-reported frontier (7689), sources (457),
exploration_runs (17) and providers (331). The corrected figures are the ones
above; `scholarships`, `approved`, `pending_review`, `rejected` and
`identity_key NULL` were already final and are unchanged.

The +3 runs are the three experiments below (JP, KR, GB). `runs +3` is what
distinguishes this table from the earlier draft's +2, which counted the GB run
before its `exploration_run` row had been written.

Invariants:

```
identity_key NULL == 0             PASS
approved before == approved after  PASS  (40 == 40)
duplicate identity_key groups     PASS  (0)
invalid extraction_status values  PASS  (0)
alembic head unchanged            PASS  (a4c7e91b2d05)
no auto-approval                  PASS  (0 new rows at all)
security boundary                 PASS  (no bypass added; url_safety/robots
                                        enforced per request as before)
```

**No stop condition from STEP 14's security or data-integrity groups was
triggered.** Database integrity held through three live runs.

## 20. Limitations

1. **0 of 3 runs completed.** Every figure is a floor from a truncated run, not
   a measurement of the engine's full behaviour.
2. **Extraction was never reached** (1 relevant page in 160), so the entire
   extraction → identity → dedup → review path is unmeasured on live data.
3. **The corpus is now more contaminated, not less.** Frontier +1209, sources
   +91, raw_documents +10, runs +3, `Σ queries_executed` 1601 → 1879. Another
   baseline attempt must still start from engine-produced records only.
4. **8 of 18 runs carry `status='failed'`** and none of the 18 is a completed
   run from this experiment. Breakdown: 4 historical 2026-10-04 runs, the
   historical orphan `8691b294` (KR, closed automatically by the KR run's
   stale-run handling), and the 3 runs executed here. The other 10 are earlier
   `completed` runs that predate the corrected harness, so none of the 18 is
   usable as a baseline sample.
5. Family attribution, duplicate decomposition and funding distribution are
   unreportable for the structural reason that no scholarship rows exist.
6. Single sample per country; no repetition, so run-to-run variance is unknown.

## 21. Historical Reference

The `26.0 queries / approved scholarship` figure is unchanged in status:

```
~26.0 = 1039 queries / 40 approved   -- HISTORICAL CONTAMINATED REFERENCE
approved by provenance_origin: unknown 18, phase3_acquisition 13, exploration 9
Live Σ queries_executed is now 1879, up from the 1039 that figure used.
```

It was **not** used as a target, and no comparison to it was made anywhere in
this experiment. It is recorded only so the next reader knows why the corpus
aggregate it came from is no longer reproducible.

## 22. Verdict

```
BASELINE FAILED
```

**Exact reason:** a pre-existing engine defect terminates every exploration run
mid-frontier, so no run reaches a completed state and no discovery yield is
measurable.

### Root cause

`sqlalchemy.orm.exc.ObjectDeletedError: Instance '<DiscoveryFrontier at
0x...>' has been deleted, or its row is otherwise not present.`

Raised at `services/exploration/engine.py` in `_frontier_loop`, from
`_expand_links` reading `candidate.url` after the except handler's
`self.session.rollback()`.

A rollback discards **every uncommitted row written since the last commit**,
including frontier candidates created earlier in the same transaction. The
candidate object survives in the identity map but its row no longer exists, so
the next attribute access triggers a refresh that finds nothing and raises.

The existing comment at that site claims this class of failure was fixed:

> "One bad candidate therefore killed the whole run... Capturing the value first
> makes the handler total."

That fix captured `candidate_url` (a string) before the `try`. It did not
address the object the handler still touches afterwards
(`mark_failed_transient(candidate, ...)`). The crash was reduced in scope, not
eliminated.

**This is not a new defect.** All four historical 2026-10-04 runs carry the
identical `fatal_error`:

```
bb7869ff KR  failed  Instance '<DiscoveryFrontier at 0x...>' has been deleted...
9e54c6fd ID  failed  Instance '<DiscoveryFrontier at 0x...>' has been deleted...
5036e90a GB  failed  Instance '<DiscoveryFrontier at 0x...>' has been deleted...
6a17ae93 SG  failed  Instance '<DiscoveryFrontier at 0x...>' has been deleted...
8691b294 KR  failed  run interrupted; finalized by a later run start   (orphan)
```

**7 of 7 live runs have now failed this way.** Every number the engine has ever
produced came from a truncated run.

### Why the experiment stopped after three countries

STEP 14 lists "acquisition subsystem failure that invalidates measurement" as a
stop condition. With the signature confirmed identical across two countries and
present in all four historical runs, a fourth run was a known outcome. It was
not executed.

### Fix required before any baseline can succeed

The handler must not touch the candidate ORM object after a rollback. Either:

- re-fetch the row by primary key after rollback and skip it if absent; or
- record the failure through a statement-level UPDATE keyed on
  `candidate_id`, which needs no live instance.

Either is a small change. **It was deliberately not made here**, because this
phase's instruction is explicit: do not change the system while measuring. A
baseline produced by an engine modified mid-experiment would not be a baseline.

## 23. Next Experiment

```
BASELINE FAILED
      ↓
Fix the rollback/expired-instance defect in _frontier_loop
      ↓
Re-run the same four countries, one fresh run each
      ↓
BASELINE ESTABLISHED (only if runs complete)
      ↓
Then, and only then, analyse the bottleneck
```

Two bottlenecks are already visible from these three runs and will be
quantifiable once runs complete:

1. **Authority resolution costs 6.7 search calls per discovery call** (242 vs
   36). If this ratio holds, it is the dominant cost in the engine.
2. **Only 1 of 160 fetched pages was scholarship-relevant** (0.6%), which is
   what starves extraction. The recurring "official but yielded no scholarship
   pages (3 links)" log line points at index→detail expansion.

Neither should be acted on before the engine can complete a run.