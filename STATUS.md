# Polaris — Living Status

**This is the single current-status document.** Everything under
`docs/progress/`, `docs/audit/`, and `docs/project-status.md` is a dated
snapshot: true (or not) on the day it was written, not a statement about
today. When a number here disagrees with a snapshot, this file wins —
and if this file is stale, fix this file, do not write another snapshot.

Last verified: **2026-11-24** on branch `develop` (HEAD `780cf87`),
clean clone, Python 3.12, PostgreSQL 16, Node 24.

## What Polaris is

Global scholarship intelligence platform: official sources → discovery →
deterministic extraction → dedup → human review (only `approved` records
are public) → deterministic matching. FastAPI + PostgreSQL backend,
Vue 3 frontend. See `README.md` for how to run it and `PRODUCT.md` for
product intent.

## Verified working (2026-11-24)

| Check | Result |
|---|---|
| Alembic `upgrade head` on empty DB | Pass — 20 revisions, 18 tables |
| API `GET /health` | `{"status":"ok","database":"ok"}` |
| SPA served by API from `frontend/dist` | Pass |
| Publication boundary | Pass — 19 seeded `pending_review` records, public API returns `total: 0` |
| Admin review auth gate | Pass — no token rejected, valid token accepted |
| Ruff | Pass |
| Frontend vitest | 20/20 pass |
| Frontend build | Pass — index bundle 120.51 kB (gzip 46.51 kB) |
| Frontend typecheck (`vue-tsc --noEmit`) | Pass |
| Backend unit tests (`-m unit`) | 272 passed |
| Backend full suite (migrated DB) | 1917 passed, 9 failed, 137 skipped (2026-11-24, after the review fixes below; the 9 failures are blocker 2 only) |
| Coverage | 83.54% (CI gate is 85% — see blockers) |

The Docker Compose path was **not** verified in this run (no Docker in
the verification environment); PostgreSQL was installed natively instead.
Compose remains unverified until someone runs it from a clean machine.

## Known blockers and gaps

1. **Test setup is order-dependent (real bug) — FIXED 2026-11-24.**
   `tests/conftest.py` created tables with `Base.metadata.create_all`,
   which does not create the CHECK constraints added by Alembic
   migrations, so the 5 controlled-vocabulary DB-enforcement tests
   failed on a `create_all` DB and passed on a migrated one. The
   fixture now runs `alembic upgrade head` and refuses a legacy
   create_all database with instructions to recreate it. The
   vocabulary tests pass on a fixture-built database.
2. **9 security tests are environment-sensitive.** The
   `url_safety`/robots tests perform real DNS resolution and assume
   public answers. In a sandboxed network where every external host
   resolves to a fake-IP range (e.g. 198.18.0.0/15), the code correctly
   fail-closes and the tests fail before their assertions. They need a
   normal-DNS environment (CI) to pass; do not "fix" them by weakening
   `url_safety`.
3. **Coverage gate (85%) is not met in this environment: 83.54%.**
   Part of the gap is downstream of blocker 2; part is known low
   coverage in discovery/orchestrator code (`services/ingestion/discovery.py`
   27%, `country_orchestrator.py` 38%).
4. **Data tests are unverified.** 123 tests marked `data` need the
   development knowledge-base database, which is not in this repo.
   Against an empty catalogue they fail/skip as designed. They can only
   be verified with a dump of the development DB.
5. **Catalogue numbers in older docs conflict** (41 vs 142 vs 145
   approved, on different dates). No live catalogue count is claimed
   here because the development DB was not available in this run.
   Measure it from the DB, then record it here with its date.
6. **No stable release yet.** `main` still only has the first commit;
   all work is on `develop`. Merge `develop` → `main` and tag a
   baseline once blockers 1–2 are understood in CI.
7. **Product/data priorities are unchanged** from
   `docs/progress/AS-IS-RECOMMENDATION-2026-11-09.md`: precision →
   review throughput → catalogue completeness → only then scale
   discovery. Approval rate was 20.7% and only 51% of approved records
   had a deadline at that snapshot.

## Repo hygiene (cleanup/phase-0)

- Root experiment output removed from git (`polaris.db`,
  `mofa_view_*.html`, `_strings_*.txt`, `p*_metrics*.json`) and covered
  by `.gitignore`. These files are run output, not source.
- `PHASE2_STATUS.md` (2026-09-20, long superseded) moved to
  `docs/archive/PHASE2_STATUS-2026-09-20.md`.
- `scripts/` is inventoried in `scripts/README.md`: operational runners
  vs one-off milestone scripts. Milestone scripts were **not** moved —
  tests reference some of them by path.

## Review fixes (fix/review-1-and-3, 2026-11-24)

Fixes #1 and #3 from the 2026-11-24 deep review (discovery / data /
frontend), on branch `fix/review-1-and-3`:

- **Brunei & Malaysia discovery restored on Linux.** Config files
  renamed `BN.json` → `bn.json`, `MY.json` → `my.json` (the loader
  looks for lowercase); all 12 configs now load. New regression test
  `tests/unit/test_country_configs.py` loads every config and guards
  the filename case and the `.ac.uk` copy-paste.
- **Malaysia config cleaned:** `.ac.uk` removed from
  `soft_domain_signals` (it belongs to GB, not MY).
- **Germany config:** `.daad.de` added ahead of `.de`, so the
  `official_domain` query family produces a valid `site:daad.de`
  query instead of only `site:de`.
- **Freshness is now visible:** `last_verified_at` added to the list
  summary (was detail-only) and shown on every scholarship card
  ("Verified <date>", omitted when never recorded) and as a fact on
  the detail page ("Not recorded" when null).
- **Deadline sorting:** list endpoint gained `?sort=deadline|name`
  (default `deadline` — soonest first, no-deadline records last);
  Discover gained a "Sort by: Closing soonest / Name A–Z" control,
  kept in the URL.

Verification in this run: ruff clean; the 4 new config tests pass by
direct invocation; frontend vitest 20/20, build and vue-tsc pass;
the deadline-order SQL compiles against the Postgres dialect.
**Not yet run here:** the backend API test suite needs a live
disposable PostgreSQL (none is installed in this VM), so run the
full suite on a machine with Postgres before merging. The remaining
review items (#2 verification calibration, #4 URL pre-filter, #5
pipeline wiring/freshness sweep, #6 benefits fabrication) are untouched.

## How to re-verify

```bash
# Database (disposable, name must end _test or _scratch for pytest)
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/polaris_scratch
alembic upgrade head
python scripts/seed_source_registry.py
uvicorn api.app:app --port 8000   # then: curl localhost:8000/health

# Backend tests against the migrated DB
POLARIS_TEST_DATABASE_URL=$DATABASE_URL python -m pytest tests/ -q

# Frontend
cd frontend && npm ci && npx vitest run && npm run build && npx vue-tsc --noEmit
```

## Review fixes, second batch (fix/review-1-and-3, 2026-11-24)

Fixes #2, #4, #6 from the same deep review, plus the test-setup fix
(blocker 1). Each is its own commit with regression tests.

- **Verification gate reachable again for subdomain sources.** The
  authority resolver stores the registered domain, but the engine
  compared it against the candidate's full host, so
  `org_identity_match` (the +0.25 signal the 0.75 auto-verify threshold
  cannot be reached without) never fired for subdomain sources.
  Comparison is now registered-to-registered on both sides
  (`org_identity_matches` in `services/exploration/engine.py`).
- **Frontier retry backoff honoured.** `record_failure` stamped
  `next_retry_at`, but `claim_next` never read it: a transiently failed
  candidate was re-claimed immediately, burning its attempt budget and
  hammering the failing source. `claim_next` now skips candidates
  inside their backoff window.
- **Extraction no longer fabricates benefits or research experience.**
  Benefit flags were bare keyword mentions, so "tuition is not
  covered" recorded tuition as covered; detection is now
  negation-aware. `research_experience` was "Preferred" on any page
  containing the word "research"; it is now extracted only from an
  explicit required/preferred statement, else left `None`.
- **Year-less named programmes outside collection parents are ranked.**
  `classify_page` only promoted a year-less programme page under a
  collection-named parent, so pages like Campus France's
  `/en/eiffel-scholarship-program-of-excellence` scored 0.40 and were
  never fetched. A final segment with a programme head noun plus a
  proper-name token now earns the named-programme tier; pure-vocabulary
  hub segments stay unpromoted, and promoted pages are still
  intent-classified from content before extraction.

Verified after this batch: backend full suite 1917 passed / 9 failed
(blocker 2 only, unchanged from baseline) / 137 skipped; frontend
vitest 20/20, build and typecheck pass; Ruff clean.

## Review fixes, third batch (fix/review-batch-a, 2026-11-24)

The remaining actionable items from the same deep reviews, as PR #3.

- **CandidateAnalyzer is SSRF-guarded.** It fetched untrusted
  search-result/link URLs unchecked; it now applies the ingestion
  `url_safety` policy (public-DNS validation before fetch,
  redirect-chain revalidation after).
- **An inferred country no longer publishes as fact.** The extractor's
  `country_inferred_from_source` flag is persisted by the mapper; the
  quality gate assesses an inferred country as UNKNOWN (blocking, not
  overridable). `country_id` is now correctable in review — including
  confirming the inferred value in place, recorded as a reviewer act.
- **The freshness sweep runs.** `pipeline_run.py` (the scheduled entry
  point) now calls `reclassify_deadline_states` once per run and
  records the count; previously only tests ever called it, so expired
  records presented as active indefinitely. `--no-freshness` opts out.
- **Stored fields reached the API.** Detail responses now include GRE,
  age limit, recommendation/motivation letters, CV and passport
  requirements, and the university. New `GET /scholarships/countries`
  lists countries with at least one published record.
- **Frontend structure.** Compare renders one layout per viewport
  (stack below 48rem, table above) instead of both; IELTS/TOEFL read
  "Not mentioned in the source" when unrecorded instead of the false
  claim "Not required"; country dropdowns load from the new endpoint
  (the two hardcoded lists, 12 vs 10, are gone); match-form experience
  radios are labelled as experience levels while keeping their stored
  vocabulary values.

Verification: backend 1939 passed / 11 failed locally — the 11 are
the sandbox-DNS set, byte-identical on clean `develop`; CI on PR #3
concluded **success**. Frontend 20/20, typecheck, build pass.

Still open, by design (see PR #3): exploration engine is not wired
into the nightly pipeline (scheduling/cost decision); PDF candidates
are still rejected on the frontier path; funding amounts and a
description column need migrations; extractor language-score fields
remain unfilled (Phase 1 precision).

## Discoverability essentials (feat/discoverability-essentials, 2026-11-24)

From the follow-up improvement audit, the small high-impact set:

- **Sitemap + robots.** The app serves `/robots.txt` (API disallowed,
  sitemap advertised) and a dynamic `/sitemap.xml`: static routes plus
  one URL per published scholarship (same predicate as the detail
  endpoint), `lastmod` from `last_verified_at`. Previously a crawler
  found neither, and the client-rendered SPA exposed no record URLs.
- **Cache headers.** Public catalogue GETs carry
  `Cache-Control: public, max-age=300`; the catalogue changes nightly,
  so five minutes of shared cache is well inside its change rate.
  Review/admin and the matching POST are untouched.
- **Funding filter.** `?funding=` on the list endpoint (equality on the
  controlled vocabulary) and a Funding select in Discover with full
  URL/chip/clear-all plumbing. The sidebar note that announced the
  funding filter as unavailable is corrected.
- **Deadline countdowns.** Badges now read "Closes today / tomorrow /
  in N days" up to 180 days out (arithmetic on the stated date), plain
  "Active" beyond that.

Verification: backend 1943 passed / 11 sandbox-DNS failures (identical
set on clean `develop`); frontend 22/22, build, typecheck; Ruff clean.

## Review UI (feat/review-ui, 2026-11-24)

The Phase 2 throughput bottleneck: curation was API/CLI only. There is
now a reviewer surface at `/review` (footer link, operator token
sign-in; token + reviewer name kept in the operator's browser only):

- queue metrics (pending / published / rejected / needs-correction /
  approval rate) and the pending list with blocking/conflicting flags;
- the full reviewer packet: publishable verdict, per-field quality
  with the gate's explanations, extracted facts, official source link,
  audit history;
- decisions: approve (with an explicit override option the server may
  still refuse), reject and send-back (reason required);
- corrections for deadline, degree, funding, official URL and minimum
  GPA — diffs only, reason required, record re-queues by default;
- one-click country confirmation for records blocked on an inferred
  country. To make that possible the packet identity now carries
  `country_id` (the only backend change; the patch-request docs list
  it as editable, matching the service).

The view is a thin client: every rule stays in ReviewService.
Verified end to end against a live server (401 without a token;
approval through the API published a seeded record into the public
catalogue). Backend suite unchanged at 1943 passed / 11 sandbox-DNS
failures; frontend 27/27, build, typecheck; Ruff clean.

## Search quality + rate limiting (feat/search-and-rate-limit, 2026-11-24)

- **Search.** `search_approved` matched only the scholarship name as a
  substring. It now matches name, provider name and field of study,
  plus a pg_trgm word-similarity fallback (> 0.6, queries ≥ 4 chars)
  for typos — thresholds measured against real programme names (a
  one-letter typo in "fulbright" scores ~0.78; unrelated terms score
  0). Migration `d4e5f6a7b8c9` installs pg_trgm and GIN trigram
  indexes on both name columns. Discover's search box now says what
  it searches.
- **Rate limiting.** New sliding-window middleware (`api/rate_limit.py`)
  budgets per client: 60/min matching POST, 120/min other public
  writes, 1200/min reads; 429 + Retry-After past the budget. The admin
  surface is exempt (token-gated). In-process counters (per-worker in
  multi-worker deployments); `POLARIS_RATE_LIMIT=off` disables it.

Verification: backend 1952 passed / 11 sandbox-DNS failures (identical
set on clean `develop`); 9 new tests cover provider/field/typo search
and the limiter policy + 429 behaviour; Ruff clean. The limiter does
not trip the test suite at production budgets.

## Detail-page meta prerender (feat/detail-meta-prerender, 2026-11-24)

Detail pages served the home page's static title/description for
every programme. `GET /scholarships/{id}` now runs before the SPA
catch-all and, for a published record, injects its real title, a
description composed only from fields the record carries, canonical
URL, og tags and schema.org JSON-LD into the shell (composition in
`api/detail_meta.py`, all extracted values escaped per context).
Unpublished or malformed ids get the plain shell — no name leaks,
the SPA renders its own not-found state. Response carries the
catalogue's `Cache-Control: public, max-age=300`.

Verification: backend 1960 passed / 11 sandbox-DNS failures; 8 new
tests (meta composition, escaping, HTTP wiring — the HTTP tests skip
where frontend/dist is absent, as in CI's pytest job, which does not
build the SPA); live-server smoke test confirmed a published record
serves its own title/JSON-LD and an unknown id the generic shell.

## Intelligence Phase A: LLM extraction (feat/llm-extraction-phase-a, 2026-11-24)

The first non-deterministic layer, deliberately kept under
deterministic control. New package `services/intelligence/`:

- `gemini.py` — Gemini via Google AI Studio, designed around the free
  tier: 4s client-side throttle (~15 RPM), bounded 429 backoff, JSON
  mode at temperature 0, one call per record. Env-only config
  (`GEMINI_API_KEY`, `POLARIS_LLM_MODEL` default gemini-2.5-flash);
  no key means the layer is off and the pipeline is complete without it.
- `extraction.py` — asks only for fields the deterministic extractor
  structurally misses (IELTS/TOEFL/GPA numbers, interview/result/
  study-start/open dates, experience levels, benefit provision). A
  value is admitted only with a verbatim evidence quote a
  deterministic verifier finds in the stored document, normalised
  against the house rules (plausible dates, IELTS 0–9 half steps,
  TOEFL 0–120, controlled experience vocabulary). Benefits move only
  towards True, on a quote stating provision.
- `scripts/enrich_records.py --llm` runs the pass after the
  deterministic one, `--llm-max-calls` (default 50) as the run budget.
  Proposals are written through `ReviewService.correct` with the quote
  in the reason and actor `llm-enrichment`: same version/audit/
  provenance trail as a human edit, and the record's review state
  never changes — the gate and the reviewer still publish.

Not in scope yet: GRE, age limit, motivation/CV/passport/recommendation
fields (not in correct()'s editable set), frontier triage/dedupe
embeddings (Phase B), semantic search (Phase C). A live run needs a
real AI Studio key; all tests use a fake transport.

Verification: backend 1978 passed / 11 sandbox-DNS failures; 18 new
tests (client throttle/retry/quota behaviour, evidence gate,
normalisation, and an integration test landing proposals through
correct() with provenance intact); Ruff clean; `--llm` without a key
exits 2 with setup guidance.

## Nightly acquisition + PDF candidates (feat/pipeline-discovery-and-pdf, 2026-11-25)

Two deep-review items closed:

- **(a) Scholarship acquisition is wired into the nightly pipeline.**
  `pipeline_run.py --discover` previously hard-coded
  `run_scholarship_discovery=False` — it grew providers but never the
  catalogue. It now runs registry acquisition by default (bounded by
  the run's per-source page budget, `scholarships_persisted` in the
  run record), with `--no-scholarship-discovery` as the opt-out. No
  search budget is spent; paid Serper exploration stays manual, a
  decision still open with Saburo. Also fixed: enrich_records' `--llm`
  attributes were missing from this script's argument object, which
  had silently broken nightly enrichment since PR #8 — an integration
  test now runs the real enrich step to keep that contract visible.
- **(b) PDF candidates flow through the discovery analyzer.** A PDF
  (URL suffix or content type) is fetched as bytes and read via the
  ingestion connector's existing PDF text path; encrypted/malformed/
  scanned PDFs become a diagnosable `pdf_unreadable` error, and PDF
  links on a page are kept as candidates instead of skipped as
  binaries. Title = the document's first text line; the text feeds
  the same classify/extract flow as HTML.

Verification: backend 1984 passed / 11 sandbox-DNS failures; 6 new
tests (2 pipeline wiring incl. the enrich contract, 4 analyzer PDF);
Ruff clean; `--plan-only` smoke OK.

Still open from the review queue: funding amounts + description
(migration; needs Saburo's amount-semantics decision first),
extractor language/eligibility fields as measured Phase 1 precision
work, coverage ratchet to 85, deploy decision + backups,
develop→main baseline.

## Coverage ratchet to 85 (feat/coverage-ratchet-85, 2026-11-25)

The gate's own rule — raise 83 only in the same commit that adds
tests for the two legacy ingestion modules — is now satisfied:
`services/ingestion/discovery.py` 27% → 98% and
`country_orchestrator.py` 38% → 96% (15 new integration tests, real
DB, connector/pipeline seamed out), total coverage 85.47% measured
locally on an empty test database, and `--cov-fail-under` in CI is
85 with the comment updated. Behaviour pinned along the way: a
freshly saved RawDocument stays `pending`, so the same discovery
run's reprocess pass extracts it twice (downstream dedup makes it
wasteful, not wrong) — recorded here rather than silently "fixed"
in a coverage PR.

Note for local runs: `polaris_scratch` currently holds the triage
bootstrap corpus (47 reviewed records), and two catalogue tests that
assume an empty DB fail against it locally; on a fresh `*_scratch`
database the suite is at the known 11 sandbox-DNS failures only.
CI is unaffected (empty database).

Still open: extractor language/eligibility fields
(Phase 1 precision), Serper nightly decision, deploy decision +
backups, develop→main baseline. Funding amounts + description were
decided (semantics A) the next day and are recorded below.

## Funding amounts as stated + description (feat/funding-amounts-a, 2026-11-26)

Saburo decided funding semantics **A** on 2026-11-26: store the amount
exactly as the official page states it. This closes the funding-amounts
+ description item from the review queue.

- **Schema.** One migration (`a9b0c1d2e3f4`) adds `funding_amount`
  (Numeric), `funding_currency` (ISO 4217 as stated, no FX conversion),
  `funding_period` (`total` / `per_year` / `per_month` / `per_semester`
  / `one_off`, a new controlled vocabulary in
  `services/domain/vocabulary.py`), `funding_duration_months` (only when
  stated), and `description` (Text), with the CHECK constraints landing
  in the same migration as the columns, per the `e7f8a9b0c1d2` lesson.
  Tuition waiver keeps amount NULL (never 0); unknown stays NULL.
- **Extraction.** The deterministic extractor admits a figure only when
  one sentence carries amount + period wording + a funding noun; each
  figure is judged on the words around it, so a page stating both
  tuition and a stipend yields the stipend figure, never a sum and
  never the tuition figure with the stipend's period. The evidence
  sentence is kept in provenance. `description` is the page's own first
  substantive paragraph, capped at 500 characters, never written copy.
- **Surfaces.** Public summary/detail schemas, detail-page meta (the
  excerpt leads; the amount renders as e.g. "€2,100/month"), card,
  detail and compare views (NULL amount reads "Not mentioned in the
  source"), and the review boundary: amount/currency/period/duration/
  description are correctable and proposable, with ISO-currency,
  controlled-period, non-negative-amount and positive-duration
  validation at `correct()` instead of an IntegrityError at flush.

Verification: backend 1994 passed / 28 failed on a fresh local test DB,
where the 28 are byte-identical to clean `develop` in the same
environment (11 sandbox-DNS + 17 that need the pg_trgm extension the
local test server lacks; CI's PostgreSQL 16 has it). 27 new backend
tests + 2 new frontend tests; migration upgrade/downgrade cycle
verified; frontend 29/29 + build + typecheck; Ruff clean.

Still open from the review queue: extractor language/eligibility
fields as measured Phase 1 precision work, Serper nightly yes/no,
deploy decision + backups, develop→main baseline. PR #10 (coverage
ratchet) merged into `develop` on 2026-11-28; this branch was rebased
onto it the same day, keeping both STATUS sections.

## Phase 1 slice: IELTS + GRE extraction (feat/phase1-ielts-gre, 2026-11-28)

First slice of the Phase 1 precision work: the deterministic
extractor no longer hardcodes IELTS and GRE to `None`.

- **IELTS.** `_extract_ielts` mirrors `_extract_toefl` with the house
  rules from LLM Phase A: band 0–9 in half steps; an explicit band
  yields `(required=True, band)`; "not required" / "waived" yields
  `(False, None)`; an unusable band (e.g. 6.3) yields `(True, None)`;
  no mention stays `(None, None)` = unknown, never a guess.
- **GRE.** `_extract_gre` admits only explicit wording (required /
  must submit → True; not required / waived → False); a bare GRE
  mention stays unknown.
- **Known limit.** The mapper still coerces `ielts_required=None` to
  False in the DB, so the concrete gains are `minimum_ielts` and
  `gre_required=True`. No provenance evidence sentence is stored for
  these two fields yet.

Verification: 13 new unit tests; full backend suite on the rebased
branch 2026 passed / 11 failed, where the 11 are byte-identical to
clean `develop` in the same sandbox environment (the sandbox-DNS /
network set); Ruff clean.

Still open from the review queue: the remaining extractor fields
(university, interview/result/study-start dates, work/publication
experience, motivation/CV/passport), Serper nightly yes/no, deploy
decision + backups, develop→main baseline.
