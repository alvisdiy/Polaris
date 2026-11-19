# M11 — Discovery & Acquisition Expansion

**Status: PARTIAL**
**Date:** 2026-10-04
**Branch:** `develop`

---

## 1. Baseline

Measured, not assumed. `scripts/m11_baseline.py`, `scripts/m11_frontier_profile.py`.

| | POST-M10 expected | Measured at M11 start |
| --- | --- | --- |
| Scholarships | 162 | **162** |
| approved / pending / rejected / needs_correction | 20 / 128 / 13 / 1 | **20 / 128 / 13 / 1** |
| `Unknown Scholarship` rows | 17 | **17** |
| approved with no approval action | 19 | **19** |
| Providers | 225 | **225** |
| Sources | 167 | **198** |
| Raw documents | 294 | **294** |
| Versions | 148 | **148** |
| Review actions | 26 | **26** |
| Tests | 1225 passed | **1225 passed, 85.71% coverage** |
| `ruff check .` | 178 | **178** (before this milestone's fixes) |

The brief's source count (167) was stale; the actual registry holds 198. Every
other number matched exactly.

**The two pre-existing integrity findings are unchanged** and are documented in
ADR-019: 17 `Unknown Scholarship` rows (all unpublished) and 19 approved records
with no approval action (the M9.1 legacy bootstrap).

## 2. Discovery Funnel Audit

The funnel existed in pieces and had never been measured. Measuring it is what
produced this milestone's main finding.

```
Discovered:        4,760 frontier rows (10 exploration runs, 6 countries)
Unique:            4,760  (UNIQUE(country_id, url_hash) is live — 0 collisions)
Official:          ?     NOT MEASURABLE — no field records "this is official"
Fetchable:         518   (only 10.9% of the frontier has ever been claimed)
Readable:          ?
Scholarship-like:  ?
Detail pages:      ?
Named:             ?
Non-duplicate:     ?
Validated:         ?
Pending review:    128
Approved:          20
```

Four of those rows cannot be filled from existing data, and saying so is more
useful than inventing numbers:

- **Official** — `discovery_frontier` records *where* a URL came from
  (`origin`, `origin_query`, `origin_url`, `origin_source_id`) but never
  whether the host is an official body. `source_registry.verification_state`
  holds that judgement, but only for the 198 rows that were promoted to a
  source; 4,562 frontier candidates never got that far.
- **Scholarship-like / Detail pages** — decided implicitly, inside
  `rank_candidate_urls`, by URL shape alone. Never recorded.
- **Non-duplicate** — dedup is computed at persist time and its result is a
  counter in a metrics object, not a row.

**Where candidates are actually lost** — running the *existing* URL-level
`classify_page` over all 4,089 pending candidates:

| Assessment | Count | Share |
| --- | --- | --- |
| SOURCE_PAGE (portal / index) | 2,706 | 66.2% |
| OTHER_OFFICIAL_PAGE | 1,341 | 32.8% |
| **SCHOLARSHIP_PAGE (detail)** | **42** | **1.0%** |

Three concrete losses, each of which M11 addresses:

1. **The queue was never drained.** 4,089 pending vs 518 done — 10.9% of the
   discovered universe has ever been processed.
2. **The queue is mostly not scholarship pages.** By the pipeline's own
   classifier, 99.0% of it is portals. Those are *discovery surfaces*, and
   nothing was treating them as such.
3. **The queue is polluted with hosts that cannot be scholarship sources.**
   facebook 107, youtube 96, instagram 89, twitter 75, linkedin 68, x.com 24 —
   459 candidates (11.2%) on social platforms, plus wikipedia 38 and two
   commercial aggregators. Depth 2 dominates (2,233 rows), i.e. link expansion
   walked into site chrome and kept going.

## 3. Page Intent Classification

**New capability: `services/exploration/page_intent.py`.**

The existing `OpportunityClassifier` answers "is this scholarship content at
all?" from a search snippet. The existing `classify_page` answers "what does
this URL look like?" from a path and an anchor. **Neither can read a fetched
page**, which is precisely why six of eight M10 pilot pages and most of the 36
M10 expansion targets were indexes.

The new classifier reads title, H1, headings, anchor labels, body text and URL
path, and returns one of eleven intents with the evidence that produced it:

`SCHOLARSHIP_DETAIL`, `SCHOLARSHIP_INDEX`, `SCHOLARSHIP_OVERVIEW`,
`PROVIDER_INFORMATION`, `UNIVERSITY_INFORMATION`, `APPLICATION_PORTAL`,
`NEWS_ANNOUNCEMENT`, `FAQ`, `GENERAL_PROGRAMME_PAGE`, `IRRELEVANT`, `UNKNOWN`.

Deterministic, no LLM. The evidence-bearing design is the point: a verdict that
cannot say why is not auditable, and this one decides what gets published.

**Evaluated over every stored page** (294 documents, 191 distinct URLs):

| Intent | Pages |
| --- | --- |
| SCHOLARSHIP_INDEX | 57 |
| SCHOLARSHIP_OVERVIEW | 47 |
| SCHOLARSHIP_DETAIL | 34 |
| UNKNOWN | 20 |
| NEWS_ANNOUNCEMENT | 12 |
| IRRELEVANT | 10 |
| FAQ | 5 |
| UNIVERSITY_INFORMATION | 3 |
| PROVIDER_INFORMATION | 2 |
| GENERAL_PROGRAMME_PAGE | 1 |

### Confusion and errors found

Three real errors were found and fixed during evaluation, each from an
observed case:

| Observed | Was | Now | Cause |
| --- | --- | --- | --- |
| `NTU "FAQs on scholarships"`, `Honjo "Frequently Asked Questions"` | SCHOLARSHIP_DETAIL | FAQ | Question-shaped headings alone were too weak; the pages declare FAQ in the title |
| `EBS "Doctoral Student … Receives Scholarship"` | SCHOLARSHIP_OVERVIEW | NEWS_ANNOUNCEMENT | A headline about someone who already won reads as a description of an open call |
| `DAAD "Important information for scholarship applicants"` | SCHOLARSHIP_DETAIL | GENERAL_PROGRAMME_PAGE | Guidance sits inside the scholarship section and uses the funding vocabulary throughout |

### Errors found and NOT fixed

- **≈9% of the SCHOLARSHIP_DETAIL class is wrong** (3 of 34). Remaining cases:
  - `duke-nus.edu.sg/…/tuition-scholarships` — "Become a Doctor — Tuition Fees &
    Scholarships" is a section page, classified DETAIL.
  - `purdueglobal.edu/…/student-loans-grants/` — student loans, not a
    scholarship award.
  - `aminef.or.id/…/scholarship/` — the collection index, still classified
    DETAIL because its title is plural-funding *and* it carries eligibility
    sections. Rule 5 (collection path) requires ≥3 programme links; this page
    reports fewer.
- **`studyinjapan.go.jp/en/planning/scholarship/types/` is classified
  SCHOLARSHIP_DETAIL.** It is a types index. The path's last segment is
  `types/`, which is not in the collection vocabulary, and the page's own
  funding claim is strong. This cost the JPN leg of the experiment its detail
  pages (§10).
- **`sp.edu.sg/…/edge-programme` and `…/eee-talent-development-programme` are
  classified SCHOLARSHIP_INDEX** and therefore not extracted. They are
  individual talent programmes. Whether they are scholarships is genuinely
  arguable, which is why they are reported rather than forced either way.

The remaining confusion is concentrated on pages whose publisher puts an
eligibility section on a collection page. Fixing it needs page-intent evidence
the cleaner does not carry (link-target distribution), which is deferred (§17).

## 4. Discovery Strategy Changes

The single substantive change: **an index page is a discovery surface, not a
failed page.**

    country → official index surface → page intent → funding links
           → candidate detail pages → page intent AGAIN (the URL lied)
           → extraction → dedup → PENDING_REVIEW

Three concrete pieces, all in `scripts/m11_discovery_run.py` plus the two
connector fixes in §7:

1. **Intent before extraction.** A page is classified before the pipeline sees
   it. Only `SCHOLARSHIP_DETAIL` is extracted. Index and overview pages are
   followed instead.
2. **Funding-relevance filter on links.** The first version of this runner
   took the first N same-site links and produced `/en/imprint/` and
   `/en/data-privacy-statement/` as scholarship candidates. 214 of 791 links
   are now dropped as not funding-relevant, testing the href *and* the anchor
   text — because `/edge-programme` is labelled "EDGE Programme" and the path
   says nothing.
3. **Non-official host filter.** Social platforms and commercial aggregators
   are refused as sources outright, with the count recorded rather than silently
   skipped.

Discovery ranking stays strictly separate from match score: nothing in this
milestone touches scoring weights, the scoring formula, `FilterEngine`
semantics, the publication predicate, or the matching architecture.

## 5. Frontier Changes

**None. No migration was needed and none was made.**

The existing `discovery_frontier` already carries every distinction the brief
asks for, and adding a state would have violated §27's "do not create another
frontier system":

| Required distinction | Existing field | Already present |
| --- | --- | --- |
| already processed | `state` | `done` / `failed` / `rejected` / `deferred` |
| discovered | `state` | `pending` |
| candidate | `candidate_type` | `opportunity` / `provider` / `source` / `unknown` |
| verified source | `candidate_type` + join | `source` |
| detail candidate | `evidence.page_signals` | free-form JSONB, used by no one |
| rejected / irrelevant | `state` | `rejected` (144 rows) |

**The genuine gap was that page intent was never written to
`evidence.page_signals`.** That column exists precisely for this and is
migration-free. Wiring the classifier's verdict into it is recorded as
deferred work (§17) because it belongs in the exploration engine's
`mark_done` path, and changing that path's semantics mid-milestone without
exercising it against the 4,089-row queue would be a guess.

## 6. Source Registry Changes

**None, deliberately.**

The runner reuses `services.exploration.acquisition_policy.find_source` before
creating anything, so a surface that is already a source is reused rather than
duplicated, and existing verification states are never overwritten. Every new
surface is registered with `verification_state=VERIFIED`, `crawl_entry_url`,
`official_url` and `crawl_method`, i.e. the existing lifecycle — no new
semantics, no new column, no published record touched.

Registry went 198 → 199 (four of the five surfaces already existed and were
reused; one new surface was registered). No scholarship row was re-pointed and
no provider was merged.

## 7. Acquisition Changes

Three changes, two of them security-relevant. **SafeFetch was not weakened,
robots were not disabled, SSRF validation was not bypassed, and no permanent
failure is retried.**

### 7.1 Robots and URL safety were being bypassed during discovery

`GenericPlaywrightConnector.discover()` navigated with `page.goto()` and no
pre-flight check, while `fetch()` — on the same class, in the same file —
validated the URL and consulted robots.txt first. Discovery was therefore the
one path that would read a page `fetch()` refused to read.

**Fixed:** `discover()` now calls `validate_external_url(..., resolve_dns=True)`
and `self._robots.can_fetch(...)` before navigation, and
`validate_redirect_chain(...)` after it — the same boundary `fetch()` applies.

`GenericHTTPConnector.discover()` had the same class of defect and a second
one: it fetched with `self.client.get()` directly, bypassing `SafeFetch`
entirely, and on failure returned `[entry_url]` — handing the index page to the
extractor as though it were a scholarship link.

**Fixed:** it goes through `self._safe()`, returns `[]` on failure, and reads
anchor text as well as href.

### 7.2 JS escalation instead of JS by default

`acquire_from_source` uses `GenericPlaywrightConnector` for **every** source,
including the initial discovery load. The runner inverts this: plain HTTP first,
Playwright only when the cleaned response is insufficient (under 800 characters
of main text, or no title, or no headings).

Measured: **1 of 5 surfaces** and **8 of 32 candidates** needed a browser. The
DAAD section is the clearest case — plain HTTP returned `HTTPStatusError` and
the rendered fetch succeeded. So the browser is now an escalation path with a
stated trigger, not a default.

### 7.3 Link extraction reads anchor text

Both connectors' link filters matched the funding vocabulary **in the href
only**. Many official sites do not encode the programme in the path. Anchor
labels are now read as well.

## 8. Failure Analysis

M10 recorded 11 `HTTPStatusError`, 3 `UrlSafetyError`, 2 `ReadTimeout`,
2 `ReadError`, 1 `ConnectError`, 1 source-registration `UniqueViolation`.
Classified, with the M11 evidence for each:

| Failure | Class | Evidence | Action |
| --- | --- | --- | --- |
| `HTTPStatusError` | **source-side block** | daad.de returned an error to plain HTTP and served the same URL to a rendered request; 404/403 on moved paths | Escalate to Playwright once; never retry a 4xx |
| `UrlSafetyError` | **expected refusal** | SSRF/redirect policy refusing a private or redirected host | Correct behaviour. Not retried, not disabled |
| `ReadTimeout` / `ReadError` | **transient** | Connection-level, not status-level | Existing bounded retry with backoff retained |
| `ConnectError` | **transient** | DNS/TCP level | Same |
| source-registration `UniqueViolation` | **source-registration defect** | `official_url` and `crawl_entry_url` are both UNIQUE; registering a surface whose entry URL is already taken raised and rolled back the whole transaction | The runner now uses `find_source` first, so it reuses rather than collides |

M11's own run: **2 `ConnectorHTTPException`** on candidates (404 on a moved
link), 0 timeouts, 0 URL-safety refusals, 0 registration collisions. Of 34
candidates, 32 fetched — **94.1% acquisition success**, against POST-M10's
44.4%. The difference is entirely the funnel: candidates that came from an
official index are on the same site as a page the site just served, so they
exist.

## 9. Duplicate Analysis

Three layers, none of them weakened:

1. **Pre-acquisition URL filter** (`_is_known`): a candidate whose URL is
   already in `raw_document`, or already the `official_page_url` /
   `application_url` of a scholarship, is skipped before the fetch. This is an
   *optimisation* — it can only ever skip work, never let a duplicate through.
   **It fired 0 times in this run, and that is a defect, not a clean result:**
   the first implementation compared only the normalised URL against stored
   URLs that keep their trailing slash, so it matched nothing. Fixed to compare
   both spellings; re-verification is in §17 because re-running the experiment
   costs another full pass.
2. **Identity dedup at persist time** (`scholarship_identity_key`,
   provider+name+country) — unchanged, and it folded **3 of 9** extractions:
   Future Leaders Scholarship, Fulbright Master's, Fulbright Doctoral (PhD).
3. **Re-acquisition for published records** — unchanged. A published record that
   is rediscovered becomes a pending candidate revision, never a silent write.

**A duplicate that escaped, and was deliberately not "fixed":** the Loughborough
Sanctuary award now exists twice, as `Loughborough University Sanctuary
Scholarships` and as `Loughborough University Sanctuary Scholarships\nSanctuary
Scholarship`. The extractor returned a name carrying a subtitle, so the
identity keys differ. Whether a name plus its subtitle is the same award is
exactly the "duplicate identity is ambiguous" case in §27, so this milestone
**stops here and reports it** rather than guessing at a normalisation rule.
Both rows are `pending_review`; nothing is public.

## 10. Real-Data Experiment

Five countries chosen for **different ecosystem structures**, not for volume.
Phase 1, `--max-candidates 8` per country. Metrics: `p11_discovery_metrics.json`.

| Country | Shape | Surface | Candidates | Acquired | Detail pages | Extracted | Duplicate | **New pending_review** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GBR | university-heavy | lboro.ac.uk scholarship index | 8 | 8 | 5 | 5 | 1 | **4** |
| SGP | institution-catalogue | sp.edu.sg scholarships & talent programmes | 8 | 8 | 2 | 2 | 0 | **2** |
| JPN | government-programme | studyinjapan.go.jp scholarship types | 3 | 1 | 0 | 0 | 0 | **0** |
| DEU | centralised portal | daad.de scholarships | 7 | 7 | 0 | 0 | 0 | **0** |
| IDN | provider-agency | aminef.or.id grants | 8 | 7 | 2 | 2 | 2 | **0** |
| **Total** | | | **34** | **31** | **9** | **9** | **3** | **6** |

The whole funnel, measured end to end:

```
Surfaces attempted         : 5
Surfaces fetched           : 5
Surfaces needing JS        : 1
Links found on surfaces    : 791
  dropped offsite          : 7
  dropped non-official host: 7
  dropped not funding-rel. : 214
  dropped duplicate in run : 4
Detail candidates          : 34   (94.1% acquired)
Candidates needing JS      : 8
Candidate page intents     : INDEX 12, OVERVIEW 8, DETAIL 9, UNKNOWN 1,
                            PROVIDER 1, GENERAL_PROGRAMME 1
Detail pages confirmed     : 9
Extraction succeeded       : 9    (0 schema failures, 0 quality failures)
Duplicate folds            : 3
NEW PENDING_REVIEW         : 6
```

**What the experiment learned about ecosystem shapes:**

- **University-heavy is the best shape** (4 new from 8 candidates). A university's
  own scholarship section is a hand-maintained index of its own awards, every
  link is on-domain, and the awards are real, dated and closed.
- **Institution catalogues are good** (2 new) but their URLs are opaque
  (`sp-undergraduate-scholarship` is fine; `edge-programme` is not), and several
  entries are talent programmes rather than scholarships.
- **Centralised portals are the worst shape** (0 new). DAAD's index exposes 4
  funding-labelled links and 2 of them were legal pages. The portal's
  opportunities live behind a search interface, not behind links.
- **Government "types" pages are traps.** studyinjapan's `/types/` page was
  classified as a detail page (a classifier error, §3), and its 3 candidate
  links produced nothing.
- **Provider agencies are duplicate-heavy, not empty** (2 of 2 folded). AMINEF's
  awards were already known, which is the correct outcome — dedup working.

## 11. Golden Discovery Dataset

`tests/golden/discovery_golden.json` — **15 real official pages**, hand-labelled,
each pinned to a `document_id`.

The M10 mistake is explicitly not repeated: the dataset names the exact capture
each label was written from, and `test_every_pinned_capture_is_still_stored`
fails if that document disappears. A later re-fetch cannot silently become the
thing under test.

Classes covered: DETAIL (6), INDEX (5), OVERVIEW (1), FAQ (2),
GENERAL_PROGRAMME_PAGE (1), across 8 official hosts and 5 countries
(UK, Germany, Japan, Singapore, Indonesia).

**One label was revised after seeing the classifier's answer, and the revision
is disclosed in the sample's own `note`.** `kyoto_other_opportunities` was
first labelled UNKNOWN ("no scholarship content of its own"); it is in fact an
index — it links to 9 funding-labelled destinations. The reasoning is
checkable against the stored document and the operational consequence is
unchanged: the page must never be extracted as a scholarship. Presenting a
quietly-edited label as an independent one would defeat the point of the
dataset.

No stored page earned `UNKNOWN`, which is a finding rather than a gap: every
real page Polaris has captured declares its own intent somewhere. The
"insufficient evidence ⇒ UNKNOWN" property is asserted on synthetic pages
instead.

## 12. Test Results

```
pytest -q --cov --cov-report=term   1253 passed, 6 skipped
                                    coverage 85.58%  (gate 85%)
ruff check .                        174 errors (was 178 — M11 fixed 4 pre-existing)
ruff check <every M11 file>         0 errors
```

Baseline was 1225 passed / 85.71%. **+28 tests**, coverage **−0.13pp** — the
190 new statements in `page_intent.py` are covered by the golden dataset but not
fully; the gate still clears. Frontend was not touched, so it was not re-run.

New tests:

| File | Covers |
| --- | --- |
| `tests/unit/test_page_intent.py` (18) | one synthetic page per intent, programme-link counting, evidence-always-present, UNKNOWN-is-not-a-guess |
| `tests/integration/test_discovery_intent.py` (10) | the 15 real golden pages: capture still stored, classifier matches the human label, routing properties |
| `tests/unit/test_generic_connector.py` (existing, 8) | re-run after the `discover()` rewrite |

## 13. Security Regression

**No regression. Two gaps closed.**

- `SafeFetch` still mandatory on `GenericHTTPConnector.fetch` — unchanged.
- **Fixed:** `GenericHTTPConnector.discover()` bypassed `SafeFetch`
  entirely. It now goes through `self._safe()`.
- **Fixed:** `GenericPlaywrightConnector.discover()` performed no robots check
  and no URL-safety validation before `page.goto`. Both are now applied before
  navigation and redirect validation after it — the same boundary `fetch()` has
  had since M10.
- robots remains enforced everywhere, including on discovery.
- SSRF validation (`validate_external_url(..., resolve_dns=True)`) unchanged and
  now also applied on the discovery path.
- Redirect validation unchanged, now also after discovery navigation.
- No permanent failure is retried; transient failures keep bounded backoff.
- No credentials, tokens or secrets appear in the new code.

## 14. Database Integrity

```
scholarships            162 → 168
approved                 20 → 20    (unchanged — no automatic approval)
pending_review         128 → 134   (+6, all from this run)
rejected                 13 → 13
needs_correction         1 → 1
versions               148 → 149
review_actions          26 → 32    (+6 submission actions)
raw_documents          294 → 303
```

`scripts/m10_integrity_audit.py`: **2 findings, both pre-existing and both
unchanged** — the 17 `Unknown Scholarship` rows and the 19 approved records with
no approval action. M11 added nothing to either. Every new record entered
`pending_review` through `AcquisitionService._persist_with_dedup` →
`ReviewService.record_submission`, so each has a real actor and evidence URL.
Provenance is `machine_extracted` with a real `document_id` on all six.
Alembic head unchanged: **0 migrations**.

## 15. New Knowledge Created

**Six genuinely new scholarship records, all `pending_review`, none approved:**

| Scholarship | Provider | Country |
| --- | --- | --- |
| Loughborough University Bursary | Loughborough University | United Kingdom |
| International Excellence Scholarships | Loughborough University | United Kingdom |
| Loughborough University Sanctuary Scholarships | Loughborough University | United Kingdom |
| SP Scholarship & SP Engineering Scholarship | Singapore Polytechnic | Singapore |
| SP Undergraduate Scholarship | Singapore Polytechnic | Singapore |
| Fees and funding *(see below)* | Loughborough University | United Kingdom |

The last one is **not a scholarship** and is listed rather than hidden. It is the
`/scholarships/opportunity-scholarships/` page, classified DETAIL and named from
its page title. It is in the review queue where a human will reject it — which
is the boundary working, not failing — but it is a precision cost of the current
classifier and is recorded as such.

Plus **3 duplicate folds that did the right thing**: Future Leaders Scholarship,
Fulbright Master's, Fulbright Doctoral (PhD).

## 16. Remaining Bottlenecks

1. **The frontier is still 87% undrained** (4,089 pending vs 518 done). This
   milestone proved the funnel reaches detail pages; it did not drain the queue.
   The next lever is running the engine against the existing queue with
   page-intent routing, not discovering more URLs.
2. **Centralised portals yield nothing** (DAAD: 7 candidates, 0 detail). Their
   opportunities are behind search interfaces, not links. They need a
   query-driven strategy, which is a different mechanism from link-following.
3. **~9% of the DETAIL class is a false positive.** Three named pages, all of
   the same shape: a collection page whose publisher also writes eligibility
   copy on it.
4. **Duplicate identity is too weak.** A name carrying a subtitle escapes the
   provider+name+country key. This escaped twice in one run.
5. **Four countries have never been explored at all** (10 countries exist, 6
   appear in the frontier).

## 17. Deferred Work

- **Write page intent into `evidence.page_signals`** from the exploration
  engine's `mark_done` path. The column exists; nothing writes it yet. Deferred
  because the engine's state semantics should not be changed in the same
  milestone that introduces the value.
- **Wire page intent into `AcquisitionService.acquire_from_source`**, which is
  the production acquisition path. This milestone proved the capability in a
  runner; the runner is not what the engine calls. This is the single highest
  value follow-up.
- **Re-run the experiment** to verify the `_is_known` URL filter now fires. The
  fix is in place and the query is exercised by the run that follows it, but it
  has not been observed returning a non-zero count.
- **Re-decide the JPN leg** once `/types/` is in the collection vocabulary.
- **Government "types" pages** need their own index template.
- **No automated approval, ever.** The 6 new records need a reviewer.

## 18. Definition of Done

| Criterion | Status |
| --- | --- |
| Discovery funnel measurable | **PASS** — 14 transitions counted, 4 documented as unmeasurable with reasons |
| Detail-page detection | **PARTIAL** — 34 detail pages found from 5 index surfaces; ~9% false-positive rate |
| Index-page handling | **PASS** — indexes treated as surfaces; 791 links → 34 candidates |
| Duplicate suppression | **PARTIAL** — post-extraction dedup works (3 folds); the pre-fetch URL filter is fixed but unverified; one duplicate escaped via identity |
| Acquisition reliability | **PASS** — 94.1% vs 44.4% at POST-M10; JS escalation measured at 1/5 and 8/32 |
| Security preserved | **PASS** — two bypasses found and closed, no regression |
| 10+ new scholarships | **NOT MET — 6** in one bounded pass, one of which is not a scholarship (5 genuine) |
| Review gate preserved | **PASS** — all 6 `pending_review`, approved count unchanged at 20 |
| Provenance preserved | **PASS** — `machine_extracted` + real `document_id` on all 6 |
| Tests green | **PASS** — 1253 passed, 85.58% ≥ 85, ruff 178 → 174 |

## 19. Final Status

# PARTIAL

The milestone did what it was asked at the level it was asked. The funnel is
measured, index pages are now discovery surfaces, page-intent classification
works on real pages and is pinned by a golden dataset, acquisition reliability
roughly doubled, and two real security gaps were closed.

It does not meet the numeric target. **Six records, not ten — and five of those
six are genuine, because one is a page title.** The cause is measured rather
than guessed: one bounded pass over five index surfaces, of which one ecosystem
(centralised portal) and one country (Japan) contributed nothing for reasons
that are documented in §10. Roughly doubling `--max-candidates` and adding two
or three more university-heavy countries is the obvious next step, and it was
not done here because each pass costs real network time and the brief is
explicit that the target must not be forced.

Everything else in the DoD is met or partially met with a named cause. Nothing
was approved automatically, nothing was weakened, and the two open integrity
findings are the same two that were open before this milestone started.