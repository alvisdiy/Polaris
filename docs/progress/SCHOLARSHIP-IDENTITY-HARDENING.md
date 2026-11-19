# Scholarship Identity & Deduplication Hardening Report

**Date:** 2026-10-04
**Branch:** `develop`
**Predecessor:** `docs/progress/SCHOLARSHIP-DISCOVERY-EXPANSION.md`

---

## 1. Identity Audit

### The premise in the brief is wrong, and the correction matters

The brief opens with `153 Scholarship rows have identity_key = NULL`. Live
data says otherwise:

| Claim | Measured |
|---|---|
| 153 rows with `identity_key = NULL` | **19** |
| 153 rows with `provenance_origin = 'unknown'` | 153 |

153 is the count of rows whose *origin* was never recorded. Migration
`e1a2b3c4d5f6` had already backfilled 134 of them with an identity key.
Chasing "153 NULL rows" would have meant writing keys that already existed.

### Identity map — where a Scholarship row is born

```
Creation path                       Identity computed?          Dedup checked?
────────────────────────────────────────────────────────────────────────────────
AcquisitionService                  yes, inline (weak)         yes
  _persist_with_dedup               acq…:34                    acq…:404
services/ingestion/orchestrator     NO                         NO
  persist_scholarship               (never set)                (never checked)
DiscoveryService  ──► orchestrator  NO                         NO
services/discovery/                 NO                         NO
  scholarship_discovery
scripts/seed_manual_                NO                         NO
  scholarships.py
ScholarshipRepository.save          NO                         NO
```

Three findings, all confirmed in code and then in data:

1. **Two different identity functions existed.** `acquisition_service.py`
   lowercased and collapsed whitespace inline. `extraction_quality.py:736`
   shipped a `normalize_scholarship_name` documented as *"Canonical form used
   inside `scholarship.identity_key`"* that **nothing in the identity path ever
   called**. The docstring was describing a function that was not wired up.
2. **`ScholarshipRepository.save()` performed no dedup at all** — it was
   `session.add(); commit(); refresh()`. Every path that did not go through
   acquisition could create a duplicate silently.
3. **The partial unique index only sees rows that have a key.** With 19 rows
   NULL, 18 of them approved and publicly visible, those records were
   invisible to deduplication entirely.

### What the real duplication looks like

Zero duplicate `identity_key` values existed. The duplication was upstream of
the key: **21 groups of rows sharing one `official_page_url`**. Seven of them
are one scholarship written twice under different spellings:

```
'International Excellence Scholarships'      (approved, exploration)
'International Excellence Scholarships\nScholarship'   (rejected, unknown)
'The SP Undergraduate Scholarship'           (approved)
'SP Undergraduate Scholarship'                (rejected)
'SP Scholarship & SP Engineering Scholarship'  (approved)
'SP Scholarship and SP Engineering Scholarship\nThe SP …'   (rejected)
```

The weak normaliser could not see these as equal, so each pair got two keys.

---

## 2. Canonical Identity Design

New module `services/scholarship/identity.py` — one definition, every path.

```
scholarship_identity_key = sha256(provider_id | canonical_name | country_id)
```

### Name canonicalisation, in order

| Step | Rule | Example |
|---|---|---|
| 1 | NFKC + whitespace collapse + casefold | `Ｇｌｏｂａｌ` → `global` |
| 2 | Edge trim, **bracket-aware** | `Eiffel )` → `eiffel`; `(EPOS)` **kept** |
| 3 | `&` → `and` | `SP Scholarship & …` → `sp scholarship and …` |
| 4 | Leading **definite** article only | `The Rhodes` → `rhodes` |
| 5 | Drop a trailing **newline** segment adding no new word | `Opportunity Scholarship\nScholarship` → `opportunity scholarship` |
| 6 | Singularise a trailing funding noun | `Sport Scholarships` → `sport scholarship` |

Two rules are deliberately narrower than they first look, and each was a bug
I hit and fixed:

- **Only `the` is stripped.** An earlier version stripped `a`/`an`, which
  merged `A Star Scholarship` with `Star Scholarship`. Those are two awards.
- **The duplicate-noun rule is keyed on a newline.** My first attempt dropped
  *any* trailing funding noun already present earlier in the name, which
  turned `SP Scholarship and SP Engineering Scholarship` into
  `sp scholarship and sp engineering` — it ate a real second occurrence. A
  page title that concatenates `<h1>` and `<title>` leaves a newline; a name
  typed on one line that happens to end in "Scholarship Scholarship" does
  not. The newline is the evidence.

### Year and cycle

Digits are **preserved**. `Scholarship 2026` and `Scholarship 2027` are
different application cycles and get different keys. This architecture does
not model cycles as a separate entity, so collapsing them would silently
merge two live awards.

### Why URL is not part of identity

The live corpus decides this. Four distinct MEXT awards share one
`official_page_url`:

```
MEXT Scholarship for Japanese Studies Students
MEXT Scholarship for Research Students
MEXT Scholarship (University Recommendation)
MEXT Scholarship for Undergraduate Students
```

Two LPDP awards share one page. Two DAAD awards share one page. A URL-keyed
identity would merge six real programmes. `canonical_url()` exists, and is
used, but only to **detect** likely duplicates — never to decide identity.

### Country: kept, and the conflation is now visible

`country_id` resolves to the page's stated study destination, **falling back
to the source's country** when the page states none. Those are two different
concepts sharing one column, so an international scholarship found from two
country runs could split.

Measured on the corpus: **0 such splits exist today.** So country stays in
the key — removing it on a hypothetical would be speculation — and
`detect_cross_country_clones()` reports the condition when it does occur,
because deciding which row is real is a curation judgement, not a schema one.

---

## 3. Legacy Rows

**19 rows, all `RECONSTRUCTABLE`.** Every one has a provider, a country and a
non-blank name; `scholarship_name`, `provider_id` and `country_id` are all
`NOT NULL`.

```
RECONSTRUCTABLE:       19
AMBIGUOUS:              0
INSUFFICIENT_DATA:      0
DUPLICATE_OF_EXISTING:  0   (would be reported, not resolved)
UNIQUE:                19
```

Migration `a4c7e91b2d05` filled all 19. Applied to the dev database:

```
[identity backfill] 19 row(s) given a canonical identity_key
```

---

## 4. Deduplication Changes

### The invariant moved into the repository

```python
# services/scholarship/repository.py
def save(self, scholarship) -> Scholarship:
    identity = scholarship_identity_key(provider_id, name, country_id)
    scholarship.identity_key = identity
    existing = assess_duplicate(session, canonical_key=identity, exclude_id=...)
    if existing is not None:
        return existing          # nothing written
    ...
```

Callers no longer decide whether to deduplicate. `persist_scholarship` never
did; now it does, because it cannot route around `save()`.

`scholarship_identity_key` is now **derived, not supplied**. A path that
forgets to set the key still lands inside deduplication.

`acquisition_service.scholarship_identity_key` is kept as a thin delegate so
existing imports and tests keep working, but it now produces the *same* key as
the repository instead of a second convention.

**Refusing rather than guessing:** a row whose name canonicalises to nothing
raises `IdentityUnavailable` instead of being saved. A hash of empty strings
is a key that collides with every other incomplete row, and this database
already has 19 rows that demonstrate the cost.

### What the fix is worth, measured

Under the new canonical form, the 202-row corpus contains **7 collision
groups** — 7 genuine duplicate pairs the old key could not see. **Four of them
include an approved record**, which is why the merge policy writes nothing on
collision rather than picking a winner. Zero cross-country clones.

---

## 5. Merge Policy

Dedup **writes nothing**. When an identity is already owned, the existing row
is returned untouched and the incoming entity is discarded.

That is not a simplification, it is the whole policy. It makes three rules
unimplementable rather than merely documented:

- a rejected row cannot overwrite an approved row;
- a lower-quality extraction cannot erase higher-quality data;
- provenance cannot be silently replaced.

Callers that *intend* a refresh — re-discovery, corrected extraction — must
say so explicitly through `_merge_reacquisition` or the candidate-revision
path, both of which record what changed. Three tests assert each rule.

The migration takes the same position: a collision leaves the row NULL and is
**reported**, because choosing a survivor is a curation decision. The earlier
backfill resolved collisions by **deleting** the losing row.

---

## 6. Database Changes

One migration, one column changed. **No schema change** — `identity_key` is
already `String(64)` and the partial unique index already exists.

`a4c7e91b2d05` — `down_revision = d5e6f7a8b9c0`.

> First attempt used `b01651cfc4c4`, which forked the chain into **two
> heads**. A test now asserts exactly one head exists.

Before/after, full-table fingerprint:

```
                                        BEFORE      AFTER MIGRATION   AFTER RE-EXTRACTION
scholarship rows                             202      202              202
status breakdown                         identical   identical        identical
content digest (excl. identity_key)  03ce72fb…  03ce72fb…        03ce72fb…
rows without identity_key                   19          0                0
alembic revision                  d5e6f7a8b9c0  a4c7e91b2d05      a4c7e91b2d05
pending candidate revisions                 0          0                4
```

**The content digest is byte-identical across all three snapshots.** No row
deleted, no field mutated, no status changed. The only differences are the
two intended ones.

`downgrade` recomputes the previous weak key for rows this migration wrote,
so the pre-migration state is restorable. Tested both directions.

---

## 7. Re-extraction Result

Re-extraction was routed through `ReviewService.propose_candidate`, which
records a proposal and **publishes nothing**. Writing the new values onto a
`Scholarship` row is the exact defect `scholarship_candidate_revision` exists
to prevent.

**First dry run proposed 15 changes. Applying them unfiltered would have been
a mistake**, which is why the run was inspected before it was applied:

| Change | Count | Verdict |
|---|---|---|
| `Fully Funded` → `None` | 6 | **would erase a human-verified value** |
| `Fully Funded` → `Travel Support` | 4 | **narrows a correct broad classification** |
| `Fully Funded` (from a partner-university list) | 1 | **false positive, evidence states no funding** |
| `None` → `Living Allowance` | 4 | genuine, evidence-backed |

Two guards were added, both now tested:

1. **The cited evidence must state the classification.** `_SUPPORT_TERMS`
   requires the evidence sentence to actually contain the benefit claimed.
   This blocked the `Travel Support` proposals — their evidence was a
   benefits table with no mention of travel.
2. **Only ever fill an empty value.** Replacing a classification a reviewer
   approved is a reclassification, and the extractor is not the authority on
   it.

```
APPLIED
approved records                  40
no stored page to match            2
re-extraction errors               0
funding already correct           23
changes proposed                   4     ← NULL → Living Allowance
blocked: unsupported evidence       7
  of which would clear a value     6
blocked: reclassification          4
```

4 `candidate_proposed` review actions, each `previous_state=approved,
new_state=approved` — the record did not move.

---

## 8. Funding Evidence Integrity

400 stored documents re-extracted read-only:

```
documents measured      : 400
funding classified      : 69
classified w/o evidence : 0
```

Specific checks from Step 11, each with a test:

| Check | Result |
|---|---|
| `funding_type != NULL` only with evidence | 0 violations |
| `funding_evidence.statement` populated for every classified value | 0 violations |
| `"full-time MSc"` → not `Fully Funded` | returns `None` (3 wordings tested) |
| waiver not collapsed into tuition only | `Tuition Waiver` (distinct value) |
| no evidence → no classification | `None` → no evidence record |

---

## 9. Test Results

```
pytest:     1491 passed, 6 skipped, 0 failed   (exit 0)
baseline:   1414 passed, 6 skipped, 0 failed
new tests:  +77
```

| Suite | Tests | Covers |
|---|---|---|
| `tests/unit/test_scholarship_identity.py` | 40 | canonicalisation, year/cycle, URL, key, clone detection |
| `tests/integration/test_identity_dedup_invariant.py` | 12 | every creation path, merge policy, persistence |
| `tests/integration/test_identity_backfill.py` | 10 | migration upgrade/downgrade, no deletion, one head |
| `tests/unit/test_funding_reextraction_guard.py` | 11 | evidence grounding, downgrade prevention |
| `tests/unit/test_scholarship_repository.py` | +4 | identity derived by repository, dedup branch |

Every canonicalisation test is paired with a test that the same input must
**not** collapse. A canonicaliser that only merges is indistinguishable from
one that works.

One existing test was changed rather than deleted:
`test_save` stubbed a bare `MagicMock` session, which now answers the
duplicate lookup with a truthy object. The fixture was made realistic
(transient entity, no duplicate); four new tests were added for the branch it
was masking.

---

## 10. Coverage

```
TOTAL   7248 statements   1004 missed   86%     (gate 85%)
services/scholarship/identity.py        93%
services/scholarship/repository.py      96%
```

> **Discrepancy with the previous report.** It recorded 92.97%. That figure
> was measured over a narrower `--cov` scope. Re-run against the scope
> configured in `pyproject.toml` (`services`, `api`, `database`), the honest
> figure is **86%**. It clears the 85% gate. I report the configured number
> rather than the flattering one.

---

## 11. Database Integrity

```
scholarship rows                      202  → 202
  approved                             40  → 40
  rejected                            157  → 157
  pending_review                        4  → 4
  needs_correction                     1  → 1
rows deleted                            0
rows without identity_key              19  → 0
content digest                    identical  03ce72fb…
pending candidate revisions             0  → 4  (new table, no Scholarship mutation)
ScholarshipVersion rows               358  → 358
ScholarshipReviewAction rows           256  → 260  (+4 candidate_proposed)
```

No unexpected row loss. No unexplained mutation. The only writes were
identity keys on 19 rows and 4 candidate revisions.

---

## 12. Remaining Risks

1. **Country is both destination and discovery scope.** One column, two
   meanings. Zero occurrences today; `detect_cross_country_clones()` reports
   them when they appear. Fixing it properly needs a column recording which
   mechanism resolved the country — a schema change I did not make, because
   no current data demonstrates a need.
2. **Four approved records have an unresolved classification question.**
   Chevening (3) and LPDP (3) publish `Fully Funded`; the extractor finds no
   funding vocabulary on the stored page. That is either a page the stored
   copy does not carry, or an extractor vocabulary gap. A human must look —
   the extractor is not more authoritative than the reviewer here.
3. **Canonicalisation is tuned on 202 rows and 400 documents.** Two MEXT
   records and one LPDP pair share a URL yet remain correctly distinct, but
   that margin is measured, not proven.
4. **The migration imports the canonicaliser rather than freezing a copy.** A
   deliberate trade: a frozen copy would drift from the code that computes
   every new key, leaving the database holding two conventions. Tests pin the
   behaviour so a change fails loudly.
5. **4 pending candidate revisions await a reviewer.** Deliberately not
   auto-approved — that is the boundary this phase was built to protect.
6. **`connector_name` untouched**, per instruction. ~50 sources would move to
   a non-JS connector if honoured. Technical debt, not this phase.

---

## 13. Discovery Benchmark Readiness

`scripts/v013_discovery_benchmark.py` is ready and **has not been run against
live discovery** — live execution requires `--run` plus `SERPER_API_KEY`, and
refuses without them.

Read-only baseline, measured not assumed:

```
STAGE                            COUNT   SOURCE
country runs completed              10   exploration_run.status
queries issued                    1039   metrics.queries_executed
search results returned           1191   metrics.search_results
frontier candidates created       4760   discovery_frontier
  of which web_search              595   discovery_frontier.origin
  of which link_expansion         4165   discovery_frontier.origin
pages fetched                      400   raw_document
listing pages blocked                0   metrics.pages_skipped_listing
opportunities retained             410   metrics.opportunities_retained
scholarships persisted             135   metrics.scholarships_persisted
duplicates collapsed (identity)    133   metrics.duplicates_collapsed
scholarship rows persisted         202   scholarship
approved                            40   scholarship.extraction_status

queries per persisted scholarship : 5.1
queries per approved scholarship  : 26.0   ← baseline to beat
scholarship yield per fetched page : 50.5%
approval rate                      : 19.8%
```

**26.0 queries per approved record** reproduces the previous phase's
baseline from live data. The new 7-family query plan has not been measured —
that is what the next run is for.

Three stages print **NOT MEASURABLE** rather than a number:
`pages classified by intent`, `listing pages blocked`, and `successful
extractions`. The first two are zero because those counters postdate the 10
historical runs; the third because `extraction_succeeded` is named
inconsistently between `AcquisitionMetrics` and `ExplorationRun.metrics`. A
fabricated funnel is worse than a short one — it looks like evidence.

---

## 14. Exact Next Step

**Run the benchmark. Three country runs, the new 7-family query plan, and
measure `queries per approved scholarship` against the 26.0 baseline.**

That is the only step that answers the question this phase exists to enable:
whether increased discovery volume produces increased *unique* scholarship
yield now that duplication is controlled. Everything before it is in place —
identity is canonical, persistence is dedup-aware, the backlog is untouched,
and the 4 pending candidates are waiting for a reviewer.

Order of operations:

1. **A reviewer decides the 4 pending funding candidates.** Cheap, and it
   closes the largest outstanding question in the corpus.
2. **Then the benchmark** — `--run --countries JP,GB,SG`, compare against
   26.0.
3. **Only then** consider the operational trigger, which Step 17 defers.

Not Opportunity generalisation. Not a scheduler. Not Fellowship. The engine
still has to prove it finds more real scholarships per query before any of
that is worth building.
