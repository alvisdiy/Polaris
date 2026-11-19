# Scholarship Discovery Expansion Report

**Date:** 2026-10-04
**Branch:** `develop`
**Baseline:** `DISCOVERY-PIPELINE-FORENSIC-AUDIT.md` (`SEMI_AUTOMATED_DISCOVERY`)
**Scope:** improve Scholarship discovery breadth, funding fidelity and traceability.
No architecture was redesigned, no crawler rebuilt, no generic Opportunity
engine introduced, and **no scheduler added** (Step 17).

---

## Current State

The forensic audit established a working but narrow engine. Three facts drove
every decision below, all measured:

| Finding | Evidence |
|---|---|
| Discovery is real but unreachable | `api/app.py` registers only `recommendations`, `scholarships`, `review`; no scheduler exists |
| Query generation was **non-deterministic** | `random.Random(None)` (OS entropy) plus `run_offset = int(time.time()) % 7` |
| Funding vocabulary had **3 values** | `FUNDING_TYPES = ("Fully Funded", "Partial Funded", "Tuition Only")` |
| Page-intent outcomes were **unmeasurable** | `page_intent_counts` existed on `AcquisitionMetrics` and was never copied into the run snapshot |
| Approved funding spread | `Fully Funded` 15, `Partial Funded` 1, NULL 24 |

---

## Changes Made

| # | File | Change | Why |
|---|---|---|---|
| 1 | `services/exploration/query_generation.py` | Seeded RNG from a **sha256 of ISO2** (not `hash()`); **3 new families** (`funding`, `degree`, `ecosystem`) | Runs become reproducible across processes; three award shapes were never queried for |
| 2 | `services/exploration/config_loader.py` | Default `query_families` 4 → 7, ordered by proven yield | Wired the new families in rather than bypassing the config |
| 3 | `services/exploration/engine.py` | `run_offset` from prior-run count, not the wall clock; removed the now-unused `datetime` import | Reproducibility; a failed run can now be re-run to confirm or refute it |
| 4 | `services/domain/vocabulary.py` | `FUNDING_TYPES` 3 → 8 values; `"tuition waiver"` no longer aliases to `"Tuition Only"` | Three genuinely different awards collapsed into one published value |
| 5 | `services/ingestion/real_extractor.py` | `funding_evidence` (alias + canonical + source sentence) in `extraction_meta` | Step 9: every funding claim traceable to its wording |
| 6 | `services/exploration/engine.py` | Persist `page_intent_counts`, `pages_skipped_not_detail`, `pages_skipped_listing`, `listing_signals` | Step 13: the audit called this "NOT MEASURABLE"; now it is |
| 7 | `tests/unit/test_scholarship_discovery_expansion.py` | **35 new tests** | Step 16 |

**No migration.** `funding_type` is `String(50)`; only the controlled alias map
changed. All eight values fit in 50 characters.

---

## Query Coverage

Families 4 → 7. The three additions are bounded templates, not a Cartesian
product.

| Family | Purpose |
|---|---|
| `opportunity` | generic awards (unchanged, proven) |
| `official_source` | official sites and application pages (unchanged) |
| `localized` | native-script queries (unchanged) |
| `provider` | provider-name discovery (unchanged) |
| **`funding`** | `fully funded / stipend / tuition waiver <scholarship> <country>` |
| **`degree`** | `<education> <scholarship> <country>` asked directly |
| **`ecosystem`** | `ministry of education …`, `national … official`, `<provider> … programme` |

Measured for JP:

```
determinism (same args -> identical plan): OK
plan size: 12 (budget 12)
families: {opportunity:2, official_source:2, funding:2, degree:2,
           ecosystem:2, provider:1, localized:1}
distinct queries across 6 rotations: 50
placeholder or empty queries across all 10 countries: 0
```

**A defect caught in final verification.** The first version of this fix seeded
from `hash(config.iso2)`. CPython randomizes `str.__hash__` per process, so the
plan was reproducible *within* one process — which the original test confirmed —
but changed between runs: the same measurement returned 51 distinct queries on
one invocation and 50 on the next. The seed is now sha256-derived, and the plan
hash is identical under `PYTHONHASHSEED` 0, 1 and 999. A subprocess test pins
it, and that test was **mutation-verified**: reintroducing `hash()` makes it
fail (exit 1); restoring the fix makes it pass (exit 0).

**Step 4 honoured.** A test asserts the plan always contains queries with *no*
funding term, so funding widens the net and never narrows it. Funding
classification stays where evidence exists — at extraction.

---

## Provider Coverage

Unchanged by design. `_register_source` (`engine.py:550`) and
`AuthoritySourceResolver` already covered government, university, foundation
and international-organisation surfaces. The change is that they are now
*reachable*: the `ecosystem` family asks for those surfaces by name instead of
waiting for a generic result to surface one.

---

## Funding Coverage

**This is the measured change.** `scripts/v012_funding_coverage_measure.py`
re-extracts all 400 stored documents, read-only:

| | Before (3 values) | After (8 values) |
|---|---:|---:|
| Documents measured | 400 | 400 |
| Parse errors | 0 | 0 |
| **Funding classified** | **39** | **69** (+77%) |
| Funding NULL | 361 | 331 |
| **Classified without evidence** | — | **0** |

| Value | After | Before (would-be) |
|---|---:|---:|
| Fully Funded | 25 | 25 |
| Partial Funded | 8 | 8 |
| Tuition Only | — | 6 |
| Living Allowance | 17 | **NULL** |
| Research Funding | 8 | **NULL** |
| Travel Support | 5 | **NULL** |
| Tuition Waiver | 4 | (was `Tuition Only`) |
| Stipend Only | 2 | **NULL** |

Thirty-six pages that previously published **no funding information at all** now
carry a specific, evidence-backed classification, and **every one of the 69**
carries its source sentence. Six further pages moved from the misleading
`Tuition Only` to the accurate `Tuition Waiver`.

---

## Index → Detail Coverage

Unchanged — the audit confirmed both production paths already work
(`_expand_links`, 4,165 rows; `connector.discover()`). Per Step 6 this was
measured rather than rebuilt. The per-page expansion budget stays at 15 and
depth stays bounded; **the backlog was not deleted or widened**.

---

## Extraction Quality

`DeterministicLLMClient` left rule-based, as instructed. Added:
`funding_evidence = {"alias", "canonical", "statement"}`.

The Step 8/9 rule is enforced by test, not by comment:

```
nothing            -> None    (no evidence, no value)
full-time trap     -> None    ("Full-time MSc programmes are available")
```

That second case is the one V0.1 shipped 18 records against. "Unknown" remains
deliberately **not** a vocabulary value — a NULL `funding_type` *means* unknown,
and a string would make "we found no evidence" indistinguishable from "the
source said unknown".

---

## Deduplication

Not changed this phase, deliberately. The audit found 153 rows with
`identity_key = NULL`, and Step 10 asks for canonicalization **before**
expanding discovery aggressively. Widening discovery while dedup is
partial-id would multiply the 153-row problem rather than fix it.

`ScholarshipRepository.save` still performs no dedup check; only
`_persist_with_dedup` does. Flagged as the next blocking item.

---

## Metrics

`exploration_run.metrics` now persists what the audit called unmeasurable:

```
page_intent_counts, pages_skipped_not_detail,
pages_skipped_listing, listing_signals
```

Previously these lived only on `AcquisitionMetrics` and were dropped at the call
site, so the DETAIL/UNKNOWN/INDEX split for 559 fetched pages was
unrecoverable. Per-source values are also written to
`frontier.outcome.acquisition`.

**Still not measurable** (unchanged, stated rather than estimated): fetchable
URLs among the 3,473 pending candidates, and whole-corpus frontier→approved
conversion (confounded by 153 pre-engine rows).

---

## Test Results

```
pytest:     1414 passed, 6 skipped, 0 failed   (exit 0)
coverage:   92.97%   (gate 85%)
new tests:  35
lint:       All checks passed! on every changed file
repo-wide:  170 findings — unchanged baseline, 0 new
```

`engine.py` was checked against `HEAD`: **3 findings before, 3 after**. The
`datetime` import my change orphaned was removed; the pre-existing
`AcquisitionMetrics` import and E501 were left alone.

### Guard tests updated, not weakened

Three existing tests asserted the 3-value funding vocabulary. Each was a
deliberate ADR-018 guard, so the intent was preserved and only the pinned set
was updated:

* `test_no_cost_list_is_an_alias_for_fully_funded` — **kept unchanged**
* `test_the_funding_vocabulary_is_unchanged` → pinned the new 8-value set, plus
  two new tests: *Unknown is still not a value* and *a waiver is not Tuition
  Only*
* `test_both_vocabularies_are_still_closed_sets` → widened
* `test_the_real_cranfield_wording_yields_no_funding_type` → **kept
  unchanged**

The Cranfield golden sample was the one genuine expectation change. Its note
read *"matches none of the three canonical funding types, so NULL is correct"*
— an argument that expired when the vocabulary grew. The page actually states
`Stipend (living allowance) at the rate of £1,452 per month`, so `Living
Allowance` is evidence-backed. The note was rewritten to say so explicitly
rather than the value being quietly patched. Its `degree: null` assertion — the
"never fabricate" half — is untouched.

---

## Live Smoke Result

No full exploration run was executed. A live run requires
`POLARIS_SERPER_API_KEY`, would write hundreds of frontier rows, and could not
be attributed as an improvement from a single sample — the honest reason is
that **a one-run comparison proves nothing**.

What *was* run live, read-only, over the **400 real stored documents**:

```
documents measured      : 400
parse errors            : 0
funding classified      : 69   (was 39)
funding NULL            : 331  (was 361)
classified w/o evidence : 0
```

The database was confirmed unchanged afterwards: 202 scholarships, 40 approved,
400 raw documents, 10 runs.

---

## Remaining Bottlenecks

| # | Bottleneck | Status |
|---|---|---|
| 1 | **No trigger** — discovery still only runs from a script | Unchanged, by instruction (Step 17) |
| 2 | **153 rows with `identity_key = NULL`**, outside dedup | Deferred; should block the next expansion |
| 3 | **3,473 pending frontier candidates** | Untouched; not deleted, not widened |
| 4 | **`connector_name` ignored** | Not changed — see below |
| 5 | **Source acquisition barely runs** (193 of 205 never attempted, 1 acquired) | Untouched |

**On `connector_name` (Step 11):** the audit found `AcquisitionService`
hardcodes `GenericPlaywrightConnector`. I did **not** change it. Live
`connector_name` values are `generic_playwright` 150, `GenericHTTPConnector`
38, `generic_http` 12, `None` 4, `mext_connector` 1 — so honouring the column
would move ~50 sources from a JS-capable browser connector to one that cannot
render client-side pages. That is a **regression risk, not an expansion
enabler**. It needs a measurement, not a code change, and it is recorded here
rather than silently taken or silently dropped.

---

## Recommended Next Step

**Not** "build Fellowship". The scholarship core is not yet stable.

1. **Canonicalize identity** (Step 10) — backfill `identity_key` for the 153
   NULL rows and make `ScholarshipRepository.save` dedup-aware. Dedup must be
   sound *before* discovery volume grows; otherwise every future run adds more
   un-deduplicated rows.
2. **Re-extract the approved corpus** so the 30 newly-classifiable pages
   actually carry their funding value. Measured above; not yet applied.
3. **Then** run several real exploration runs and compare the funnel
   (queries → candidates → scholarship-relevant pages → records) against the
   pre-expansion baseline of ~26 queries per approved record. Only that
   comparison can prove query breadth bought yield.
4. **Only after that**, operationalize the trigger.

The architecture is intentionally left as-is. When Scholarship discovery is
stable, generalizing to Opportunity (Fellowship, Internship, Research Grant,
Exchange) is mechanical — the taxonomy boundary is already the right seam.

