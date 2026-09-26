# Polaris — System Design (as built)

> **Document status:** definitive design document for the reliability program (Phases A–G).
> Every statement here reflects the implementation as it exists in this repository and the
> measured results of real acquisition runs executed on 2026-09-26. No section describes
> aspirational behaviour; anything not yet built is explicitly marked **Future work**.
>
> Per the program directive, implementation **stops after this document**. No frontend
> implementation follows it.

---

## 1. Purpose and Scope

Polaris is a scholarship intelligence platform whose core promise is that its knowledge base
is *reliable*: every scholarship row is traceable to an official web source, every identity
is deduplicated, every deadline is classified honestly, and re-running acquisition never
corrupts or duplicates the knowledge base.

This document covers the full backend system as built:

- the **country exploration engine** (discovery → verification → acquisition),
- the **freshness semantics** that keep the knowledge base honest over time,
- the **matching engine** that turns the knowledge base into recommendations,
- the **API** that exposes both,
- and the **operational evidence** (tests, metrics) that the reliability claim is real.

Out of scope (explicitly): frontend implementation, multi-tenant auth, scheduled production
orchestration. See §29.

## 2. System Overview

Polaris is a single Python service (FastAPI + SQLAlchemy + PostgreSQL) with five subsystems:

```
                         ┌──────────────────────────────────────────┐
                         │            Country Exploration           │
  Serper search API ───▶ │  surfaces → frontier loop → verification │
  Playwright fetch  ───▶ │  → acquisition (per country, zero-seed)  │
                         └───────────────┬──────────────────────────┘
                                         │ persists
                                         ▼
                         ┌──────────────────────────────────────────┐
                         │   PostgreSQL knowledge base              │
                         │   provider / source_registry /           │
                         │   raw_document / scholarship (+children) │
                         └───────────────┬──────────────────────────┘
                                         │ reads (approved only)
                                         ▼
                         ┌──────────────────────────────────────────┐
                         │   Matching engine                        │
                         │   Filter → Score → Rank → Explain        │
                         └───────────────┬──────────────────────────┘
                                         ▼
                         ┌──────────────────────────────────────────┐
                         │   FastAPI  /api/v1/*                     │
                         └──────────────────────────────────────────┘
```

- **Exploration** is the write path: it discovers organizations and pages on the open web,
  verifies them, extracts scholarship data, and persists it with full provenance.
- **Matching** is the read path: it evaluates a student profile against *approved* scholarships
  and returns ranked, explained recommendations.
- The database is the contract between them. Nothing matches against data that has not been
  verified and persisted.

## 3. Design Principles

1. **Country = discovery scope.** Acquisition is driven by per-country configuration
   (`configs/countries/{iso2}.json`), never by hardcoded provider lists. A zero-seed country
   (no providers, no sources) must be acquirable from config + search alone.
2. **Provenance or it did not happen.** Every discovered entity carries structured evidence
   (`discovery_evidence.observations`, `discovered_via`, `FrontierObservation`), and every
   scholarship traces to a `raw_document` captured from its source.
3. **Never invent facts.** Missing deadlines are `unknown`, never fabricated. Bare years are
   rejected as application cycles. Extraction uses a deterministic heuristic client, and the
   system says so (§15).
4. **Cautious identity.** Uncertain organizations are never auto-merged; they become
   `needs_review`. Verified providers are never downgraded.
5. **Newer official data wins.** Re-acquisition refreshes the canonical row (deadline, cycle,
   verification) instead of creating a duplicate (§17).
6. **Degrade, don't lie.** When a subsystem loses capability (no search key, SSL failure,
   fetch error), the run records the degradation and completes; it does not fail silently and
   does not fake success.
7. **Idempotency by default.** Re-running acquisition is a no-op on the knowledge base except
   for legitimate freshness updates (§20).

## 4. Architecture Overview

Layering (dependencies point downward only):

| Layer | Location | Responsibility |
|---|---|---|
| API | `api/` | FastAPI app, request/response schemas, HTTP concerns |
| Application services | `services/exploration`, `services/matching`, `services/scholarship`, `services/ingestion` | Use cases: exploration run, matching pipeline, persistence |
| Domain engines | `engine.py`, `orchestrator.py`, `filter/scoring/ranking/explanation` | Business rules, no I/O decisions |
| Repositories | `services/*/repositories`, `services/scholarship/repository.py` | All SQL, persistence-only |
| Models | `database/models/` | SQLAlchemy ORM, FK graph |
| Config | `configs/countries/*.json` | Per-country discovery scope |
| Scripts | `scripts/` | CLI entrypoints (seeding, exploration runs, pipelines) |

Key classes:

- `CountryExplorationEngine` (`services/exploration/engine.py`) — the canonical exploration loop.
- `ProviderResolver` (`provider_resolver.py`) — multi-signal org identity resolution.
- `VerificationEngine` (`verification_engine.py`) — source verification verdicts.
- `AcquisitionService` (`acquisition_service.py`) — connector → pipeline → dedup persistence.
- `ScholarshipIntelligenceEngine` (`services/matching/orchestrator.py`) — Filter → Score → Rank → Explain.
- `MatchingService` (`services/matching/service.py`) — application service over the engine + repository.

## 5. Technology Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11 | |
| Web framework | FastAPI + Starlette | `api/app.py` factory `create_app()` |
| ORM / migrations | SQLAlchemy 2.x + Alembic | head: `c9d2e7f1a4b8` (`scholarship.deadline_state`) |
| Database | PostgreSQL | UUID PKs, JSONB evidence columns, FK `RESTRICT` |
| Search | Serper API | factory `services/exploration/search/` (`create_search_provider`, `NullSearchProvider` fallback) |
| Fetch | Playwright (browser) + HTTP fallback | `candidate_analyzer`, `GenericPlaywrightConnector` |
| Extraction | Deterministic heuristics (`DeterministicLLMClient`, `real_extractor.py`) | §15 |
| Matching | Pure-Python deterministic engines | no ML |
| Logging | `loguru` (services) + stdlib (API) | |
| Tests | pytest (389+ tests) | §25 |

## 6. Data Model

Core tables and their relationships (FK graph, all `RESTRICT`):

```
country ──< provider ──< source_registry ──< raw_document
   │            │              │
   │            │              └──< scholarship >── scholarship_version
   │            │                     │  ├── scholarship_requirement
   │            └─────────────────────┤  ├── scholarship_benefit
   │                                  │  └── scholarship_timeline
   ├──< exploration_run ──< discovery_frontier
   ├──< provider_discovery_attempt
   └──< provider_discovery_config
```

Important columns added or repurposed by the reliability program:

- `scholarship.identity_key` — SHA-256 of `provider_id|name|country_id`; canonical dedup key.
- `scholarship.deadline_state` — `active|expired|unknown|rolling|NULL` (NULL = unclassified
  legacy), indexed (`ix_scholarship_deadline_state`), migration `c9d2e7f1a4b8`.
- `provider.identity_key`, `provider.identity_confidence`, `provider.merged_into_provider_id` —
  identity resolution trail; merged rows are kept for auditability, never deleted.
- `exploration_run.metrics` — JSONB snapshot of real run counters (§24).
- `discovery_frontier` — candidate ledger with per-candidate outcome JSON and observation
  provenance; rows are history, not a queue to be purged.
- `scholarship_version` — append-only change log rows (creation is implicit; merge events are
  explicit rows with `change_summary`).

Deletion order for a country purge (FK-safe, used in Phase A and after the failed KR run):
children first (`scholarship_version` → `scholarship_benefit/requirement/timeline` →
`scholarship` → `raw_document` → `discovery_frontier` → `exploration_run` →
`provider_discovery_attempt` → `source_registry` → `provider`), executed inside one
transaction.

## 7. Reference Data and Country Configuration

Reference seeds (deliberately kept, they are *matching-engine reference data*, not acquisition
output): `scripts/seed_source_registry.py` (16 curated sources incl. MEXT, GKS, DAAD,
Chevening, LPDP, Eiffel, Fulbright, Australia Awards) and `scripts/seed_manual_scholarships.py`
(19 curated approved scholarships).

Country configs (`configs/countries/*.json`, 10 countries) define:

- `languages`, `search_locale`, `search_gl` — search shaping;
- `terminology` — scholarship/education/provider/funding vocabularies (incl. local scripts:
  奨学金, 留学生, 奖学金) used for query generation and classification;
- `soft_domain_signals` — domains that *support* officialness (e.g. `.go.jp`, `.ac.jp`,
  `.gov.sg`, `.edu.sg`, `.org.sg`); SG was corrected to drop `.com.sg`;
- `bounds` — `max_depth`, `max_candidates`, `max_pages`, `max_pages_per_domain`;
- `max_queries_per_run` — search budget (12 for JP).

## 8. Country Exploration Engine

`CountryExplorationEngine.run()` executes a bounded, durable loop:

1. **Run row first.** `start_run` commits the run row immediately (so a crash leaves evidence),
   and calls `fail_stale_running` to finalize any earlier `RUNNING` rows for the country as
   `FAILED` with `fatal_error` + `finished_at` (fix for defect E4).
2. **Seed frontier** (`_seed_frontier`): web-search surface → config seed URLs →
   *known sources* re-enqueue (Active/Provisional `SourceRegistry` rows) — this is the built-in
   refresh/revalidation path (§19).
3. **Frontier loop** (`_frontier_loop`): claim → process → mark done, bounded by
   `max_pages` and a wall-clock deadline. Every candidate outcome is recorded on the frontier
   row (`done / rejected / failed / pending / in_progress`). Errors are caught per candidate:
   the session is rolled back, the candidate is marked transient-failed with retry bookkeeping,
   and the loop continues (`_record_run_degradation` semantics). A candidate can take down at
   most itself — never the run (proven by the KR incident, §28).
4. **Finalize** (`engine.final_frontier_states`): run status, metrics JSONB, frontier state
   distribution are persisted and reported by the CLI (`scripts/run_country_exploration.py`).

## 9. Search Surface and Search Provider Abstraction

`WebSearchSurface.execute(plan, ...)` turns a query plan (generated from the country's
terminology by `query_generation.py`) into frontier candidates.

- `create_search_provider()` returns a Serper-backed provider when
  `POLARIS_SERPER_API_KEY` is set; otherwise `NullSearchProvider` degrades the run to
  seeds/known-sources/expansion with an explicit `degraded_reason` in metrics.
- The engine reports **true backend call counts** (`queries_executed`), split into
  `discovery_queries` and authority-resolution queries, so "queries" in metrics always means
  real API calls.
- Candidates are deduplicated at the frontier (`upsert_candidate` returns `created`), so the
  same URL discovered via multiple queries/links exists once with merged observations
  (run reports show e.g. 630 candidates created with 173 dedup merges for KR).

## 10. Candidate Analysis and Classification

`CandidateAnalyzer.analyze(url)` fetches (Playwright first, HTTP fallback) and extracts page
features: title, links, structured data (JSON-LD), org hints, content text, final URL.

`OpportunityClassifier.classify()` routes each page:

- `SCHOLARSHIP / FELLOWSHIP / GRANT / STUDENT_FUNDING` — opportunity family, full pipeline;
- `JOB / VISA_JOB` with reject routing — counted as `jobs_rejected` and rejected (off-topic
  pages like "farm jobs with visa sponsorship" must not become scholarships);
- `irrelevant` — rejected; `UNKNOWN / review / low_priority` — retained for broad discovery.

Classification is a **router, not a gate**: uncertain pages stay in the pipeline and are
handled by type-aware logic; they are only dropped with an explicit recorded reason.

## 11. Provider Identity Resolution

`ProviderResolver.resolve(org_name, url)` combines signals in a cautious order:

1. **identity_key match** (registered domain + normalized name + country) → reuse (conf 0.9).
2. **Same registered domain + country**: one row → strengthen/reuse (conf 0.85); several rows →
   `_merge_domain_duplicates()` consolidates them into the earliest verified row, re-points
   scholarships and sources, and marks duplicates `merged_into_provider_id` (fix for E3: the
   live SG run had minted 3× `admissions.smu.edu.sg`).
3. **Same normalized name + country** → reuse (conf 0.7).
4. **Ambiguous by name** → `needs_review` row; **never** auto-merge.
5. **No match** → new `discovered` provider with `identity_key`, `identity_confidence`,
   and the first observation appended to `discovery_evidence.observations`.

Noise filtering (fix for E1): `_NOISE_NAME_PATTERNS` + `is_noise_org_name()` reject page-chrome
candidate names (copyright footers like `-2021 © Myanmar Study Abroad`, "last updated" notices,
privacy/cookie links, leading dashboards/years) during `extract_org_identity()`; JSON-LD, org
hints, and title segments are filtered before ranking, and if nothing clean remains the
low-confidence domain fallback (e.g. `Myanmarstudyabroad`, conf 0.3) is used.

Collision safety (fix for the live KR failure): both create paths guard `flush()` with
`IntegrityError` handling — roll back the poisoned insert, reuse the existing row found by
`provider_code` or `identity_key`, and append the new observation. `needs_review` rows carry
their `identity_key`, so a second identical ambiguous candidate resolves via Signal 1 instead
of minting a duplicate.

## 12. Authority Resolution

For every scholarship-family page, `AuthoritySourceResolver.resolve()` asks: *does the
organization on the page actually own scholarship web presence?* It runs additional search
queries (sharing the run's query budget) and returns a status recorded in metrics and
`resolution_outcome`:

- `AUTHORITY_RESOLVED` — an authoritative domain was confirmed;
- `AUTHORITY_CANDIDATES_FOUND` — candidate URLs exist and are enqueued as `SOURCE` candidates
  (link expansion with provenance);
- `AUTHORITY_UNRESOLVED` — nothing found (counted, never fatal).

Authority output feeds verification (`org_identity_match`) but is **never a hard gate** —
pages without resolved authority still flow to verification with the evidence attached.

## 13. Source Verification and Registration

`VerificationEngine.verify_source()` computes a verdict from weighted signals: HTTPS,
reachability, org-identity match, provider name, scholarship content, structured data, and
title analysis.

Aggregator guard (fix for E2): `_GENERIC_OFFICIAL_SUFFIXES` plus the country's
`soft_domain_signals` determine `is_official_host` (host or registered domain endswith a
signal). A high-confidence verdict on a **non-official host** (e.g. `finaid.org`, `uncf.org`
aggregators, or any `.com` content farm) is capped at `NEEDS_REVIEW` with an explicit
"aggregator guard" reasoning instead of `VERIFIED`. The computed `official_host` signal is
stored in `verdict.signals` for audit.

`VERIFIED` sources are registered in `SourceRegistry` by `_register_source`, which is
idempotent on both unique keys (`official_url`, `crawl_entry_url`): an existing row is updated
(`verification_state`, `confidence`) instead of re-inserted — the first live JP run crashed
here; the guard is now enforced and regression-tested.

## 14. Scholarship Acquisition and Extraction

`AcquisitionService.acquire_from_source(source, max_pages)`:

1. `GenericPlaywrightConnector` discovers in-source scholarship URLs (`discover()`),
   bounded by `max_pages`.
2. Each URL is fetched and stored as a `raw_document` (checksum, `raw_content`, timestamps) —
   the immutable capture layer.
3. `run_pipeline(document_id, ...)` = loader → cleaner → extractor (`DeterministicLLMClient`
   + `real_extractor.py`) → validator. Invalid results count as `extraction_failed` and are
   skipped — nothing unverifiable is persisted.
4. Valid results go to `_persist_with_dedup` (§16).

Extraction captures: name, provider, deadline, **`application_cycle`** (AY/intake/cohort
patterns only; bare years rejected), funding type, fields of study, benefits, requirements,
timeline. `Timeline.application_cycle` was added for cycle tracking; `ScholarshipMapper` maps
it end to end.

## 15. LLM Client Honesty

`DeterministicLLMClient` is **not** an LLM and must never be presented as one. It is a
deterministic, testable pattern-matching extractor:

- `_extract_cycle` recognizes explicit application-cycle phrases ("Academic Year 2027",
  intake/cohort patterns) and rejects bare years ("Deadline: 2027" is not a cycle);
- deadline extraction is skipped entirely when `detect_rolling(clean_text)` finds rolling
  language ("applications accepted until all positions are filled") — a rolling page must not
  inherit a stale hard date;
- docstring and logs say "deterministic" explicitly.

The upgrade path (a real LLM behind the same interface) is Future work (§29). Design intent:
extraction quality may be upgraded, but the *semantics* (never invent dates, rolling beats
dates, validation gate) are fixed here.

## 16. Scholarship Identity and Dedup

`scholarship_identity_key(provider_id, name, country_id)` (SHA-256) is computed on every
persist. On a hit against an existing row, `_merge_reacquisition` folds the new observation
into the canonical row (§17) and the engine counts `duplicates_collapsed`.

Honesty note on the metric: `duplicates_collapsed` counts *every* non-persisted extraction
(merge, mapping failure, missing document). The **authoritative merge count** is the number of
`scholarship_version` rows with `change_summary LIKE 'reacquired%'` — e.g. SG shows 40 real
merge rows. Uniqueness of `identity_key` per country is verified by query in Phase F
(§30): zero duplicate groups across all six countries.

## 17. Freshness and Deadline Semantics

`services/scholarship/freshness.py` is the single source of truth for deadline semantics.

**States** (`scholarship.deadline_state`):

| State | Meaning | Query visibility |
|---|---|---|
| `active` | parsed deadline in the future | visible |
| `rolling` | page declares rolling admission — always beats a parsed date | visible |
| `expired` | parsed deadline in the past | **hidden** from approved queries |
| `unknown` | no reliable deadline parsed — state is *unknown*, never invented | visible |
| `NULL` | unclassified (legacy rows) | visible (hiding would silently drop data) |

**Rules:**

- `classify_deadline(deadline, page_text=, today=)`: rolling phrases take precedence over
  extracted dates; future date → active; past date → expired; nothing parseable → unknown.
- At persist: state is computed from the fresh capture.
- At re-acquisition (`_merge_reacquisition`): the fresh deadline/cycle wins over the stored
  one; state is recomputed; `last_verified_at` is refreshed; a version row records
  `reacquired; deadline_state=...; deadline=...`.
- Scheduled sweep: `ScholarshipRepository.reclassify_deadline_states(today=None)` moves
  `active` rows past their deadline to `expired` (skipping `rolling` rows) — designed for
  periodic invocation (§19, §29).
- Query-time gate: `get_all_approved()` and `search_approved()` exclude `expired` rows with a
  NULL-safe predicate (unclassified stay visible). `get_currently_active()` returns approved
  rows in `active|rolling|unknown` for freshness-sensitive UI.

## 18. Provenance and Versioning

Three provenance layers, each append-only:

1. **Capture:** `raw_document` rows (raw HTML/text, checksum, fetch timestamps) — the system
   can always re-derive what the source said at capture time.
2. **Discovery trail:** provider `discovery_evidence.observations` (bounded to the last 20),
   frontier outcome JSON per candidate (`FrontierObservation` with origin, query, run id,
   anchor text), source `discovered_via` with verification signals.
3. **Change history:** `scholarship_version` rows record merge events with
   `change_summary`, `source_url`, `version_number` (max+1 per scholarship). Creation has no
   version row (creation time is on the row itself); every subsequent fold-in does.

## 19. Revalidation and Staleness

Revalidation reuses the acquisition architecture rather than introducing a new one:

- **Known-source re-enqueue:** `_seed_frontier` re-enqueues Active/Provisional
  `SourceRegistry` rows every run, so verified sources are periodically re-fetched,
  re-verified, and their scholarships re-acquired → the merge path refreshes freshness.
- **Stale-run hygiene:** `RunRepository.fail_stale_running(country_id, reason)` finalizes
  orphaned `RUNNING` rows at the start of every run (no run can be wedged forever; E4).
- **Deadline sweep:** `reclassify_deadline_states()` is the cheap mechanism that ages rows
  without re-fetching (D: minimal mechanisms, maximal reuse). Scheduling is Future work (§29).
- **Identity repair:** `_merge_domain_duplicates` self-heals provider duplicates on the next
  candidate touching the same domain; `reclassify` repairs deadline states.

There is deliberately no separate "freshness daemon": every staleness mechanism is either part
of the normal run or a repository sweep callable from any scheduler.

## 20. Idempotency and Concurrency

- Frontier: `upsert_candidate` dedupes URL+country; re-runs mostly *merge* (KR run 1: 630
  created / 173 merges).
- Providers: multi-signal resolution + both unique-key `IntegrityError` recoveries (§11).
- Sources: `_register_source` idempotent on `official_url`/`crawl_entry_url` (§13).
- Scholarships: `identity_key` dedup with canonical-row merge (§16/§17).
- Durability: the run row is committed first; candidate processing commits in batches and on
  failure rolls back only the current candidate. Tests emulate the engine's commit semantics
  with savepoint-bound sessions (`rollback_session`, `join_transaction_mode="create_savepoint"`).
- Idempotency proof on real data: second runs on JP, KR, SG (§30) produced **zero duplicate
  `identity_key` groups**, merge events recorded, and net-new rows only where genuinely new
  pages were discovered.

## 21. Matching Pipeline

`MatchingService` → `ScholarshipIntelligenceEngine.match(profile, scholarships)`:

1. **Validate** (`ProfileValidator`) — reject impossible profiles.
2. **Normalize** (`ProfileNormalizer`) — casing, synonyms, defaults.
3. **Load** — `ScholarshipRepository.get_all_approved()` (expired rows already excluded, §17).
4. **Filter** (`FilterEngine`) — hard constraints (country, degree, level).
5. **Score** (`ScoringEngine`) — weighted criteria: country, degree, field of study, GPA,
   IELTS/TOEFL, research, work, leadership, funding preference.
6. **Rank** (`RankingEngine`) — descending score with total deterministic order: score →
   funding priority → deadline recency → name → `scholarship_id` as final tiebreaker (two
   identical-score rows can never swap across requests; flaky-test fix).
7. **Explain** (`ExplanationEngine`) — strengths, gaps, next steps per result.

Categories (from the matching design spec): ≥90 Excellent, ≥80 Strong, ≥70 Good, ≥60 Moderate,
else Low. Top-N default 10. The pipeline is pure Python and fully deterministic — same profile
and data produce byte-identical recommendations.

## 22. API Surface (as built)

Base: FastAPI app `api/app.py` (factory `create_app`), global 422/500 handlers, request
logging middleware, `/health`.

| Endpoint | Method | Status | Notes |
|---|---|---|---|
| `/health` | GET | **live** | liveness |
| `/recommendations` and `/api/v1/matching` | POST | **live** | `RecommendationRequest` → ranked `RecommendationListResponse` |
| `/api/v1/scholarships` | GET | **live** | list/search approved (`q`, `country`, `degree`, pagination) |
| `/api/v1/scholarships/{id}` | GET | **live** | detail (requirement/benefit/timeline), 404 unless `approved` |

**Future work** (designed, not implemented): acquisition run triggers/monitoring endpoints,
provider/source admin endpoints, scholarship freshness endpoints (`?include=expired` for
research views), auth.

## 23. Frontend (state)

`frontend/` contains an early Vue + Vite scaffold (App.vue, scholarship detail components,
index.html). It is **not part of the reliability program** and was intentionally left
untouched. The API mounts `frontend/dist` only if it exists (currently it does not serve a
built bundle). Per directive: **no frontend implementation follows this document.**

## 24. Observability

- `exploration_run.metrics` (JSONB): queries (total/discovery/failed), search results,
  candidates created + origin/type distributions, pages fetched/failed, classification
  histogram, provider created/resolved/needs_review, authority outcomes, sources verified,
  scholarships persisted, duplicates collapsed, link expansions, retries, degraded reasons,
  provenance samples.
- `engine.final_frontier_states` — the CLI report snapshots the live frontier distribution
  while the run session is still open (fix recorded in the run script).
- Structured logging: per-run lifecycle lines, per-source registration, per-merge lines
  (`merged duplicate 'X' into 'Y' (same domain)`), degradation warnings.
- API logs request method/path/status/latency per request.

## 25. Testing Strategy

Suite: **390 passed, 6 skipped, 0 failed** (2026-09-26, `/tmp/full11.txt`).

- **Unit:** freshness classifier (states, rolling precedence, condensation), provider
  resolver (normalization, identity keys, noise names incl. fallback-to-domain, same-domain
  merge, needs_review identity recovery), verification (official-host gate, aggregator cap),
  classifier, ranking (deterministic tiebreakers), URL utils, mappers.
- **Integration (DB, rollback-isolated):** exploration loop end-to-end with fake
  search/analyzer (zero-seed → candidates → providers → verification → acquisition →
  expansion → **second-run idempotency**), freshness acquisition (persist states, rolling
  preserved, newer-cycle merge, version provenance, query-time expired gate, unclassified
  visibility, reclassify sweep), frontier/run repositories, scholarship-first flow.
- **Isolation:** `tests/integration/_exploration_isolation.py` resets the test country to a
  genuinely zero-seed state *inside* the rollback-only transaction (children-before-parents
  delete of sources/providers/scholarships/raw docs left by real runs) so the canonical
  zero-seed and idempotency tests are immune to shared-DB drift; the provider-resolver unit
  tests use the same isolation. Freshness tests scope their assertions to their own rows for
  the same reason. Version provenance uses a `select()` construct (no deprecated subquery
  coercion).
- Deterministic engines are tested for byte-identical repeated output.

## 26. Operations

- CLI: `python scripts/run_country_exploration.py ISO2 [--report] [--dry-run] [--max-runtime N]`.
  Report includes real counters and frontier states; exit code reflects run completion.
- Runtime budgets: `max_runtime` minutes per run (dev runs here used 7); `max_pages`,
  `max_pages_per_domain`, `max_retries` per run bound cost and politeness.
- Migrations: Alembic; current head `c9d2e7f1a4b8`.
- Purge procedure for a country: §6 deletion order, single transaction, verified by re-count.
- Seeds: `scripts/seed_source_registry.py`, `scripts/seed_manual_scholarships.py`
  (reference data only).

## 27. Security and Compliance

- Secrets: `POLARIS_SERPER_API_KEY` via environment only; `.env` is never read by tests;
  boolean presence checks only in logs. No secrets in code, configs, or metrics.
- Fetching: per-domain delay bounds, `max_pages_per_domain` caps, robots-allowed flag stored
  per source, no login-required sources (`requires_login=False` by construction).
- Input handling: raw captures stored, never trusted for rendering; API returns structured
  fields only; Pydantic validation on all request bodies; 422/500 handlers avoid leaking
  internals.
- SQL: all access through SQLAlchemy ORM/`text()` with bound parameters.

## 28. Known Limitations

1. **KR persisted 0 scholarships** across two completed runs (8+2 sources verified, 63+57
   pages fetched): connectors ran but extraction produced no rows passing validation. Honest
   outcome, not a hidden failure; needs source-specific extraction work (Future work).
2. **Deadline extraction is conservative.** Most persisted rows are `unknown`
   (JP 32, SG 40, GB 25, ID 14, DE 19 of their totals) because pages rarely expose machine-
   parseable future dates; the system prefers unknown over invented. `active` rows appear only
   after sources publish clean dates.
3. **`duplicates_collapsed` over-counts** (includes mapping failures); authoritative merge
   counts are the `reacquired` version rows (§16).
4. **Provider names can still be weak** for pages without clean identity signals (domain
   fallback at confidence 0.3, marked in evidence) — visible but low-trust rows.
5. **Single-node execution model:** the engine is safe for one run per country at a time;
   concurrent multi-node runs would need advisory locking (Future work).
6. **KR incident post-mortem:** the original failure (one `provider_code` UniqueViolation
   aborting a 97-candidate run) was fixed with collision recovery on both create paths; the
   re-run completed all 630 candidates. The residual lesson — a candidate-level bug must never
   cost a run — is enforced by per-candidate rollback (§8) and the collision guards (§11).

## 29. Future Work

- **API/UX:** acquisition monitoring endpoints; provider/source review workflows (resolve
  `needs_review`, approve/reject); freshness-aware filters in the public API.
- **Extraction:** source-specific extractors for KR.gov patterns; pluggable real-LLM client
  behind the existing interface with unchanged semantics (§15); structured-deadline parsing
  (JSON-LD `Event`/`Offer` dates) to convert `unknown` → `active`.
- **Operations:** scheduler for periodic per-country runs + `reclassify_deadline_states`
  sweep; multi-node advisory locks; alerting on degraded runs.
- **Coverage:** remaining configs (AU, CN, FR, US) have configs but no 2026-09-26 acquisition
  runs in this program.

## 30. Appendix — Real Acquisition Evidence (2026-09-26)

All runs: real Serper queries + Playwright fetches, 7-minute budget, `max_runtime 7`,
dev machine. Run rows carry the full JSONB metrics (§24).

**Runs executed** (all `completed`):

| Country | Run | Queries | Candidates (dedup merges) | Pages fetched | Providers +created/resolved | Sources verified | Scholarships persisted | Dup collapsed | Retries |
|---|---|---|---|---|---|---|---|---|---|
| JP | `3f8d6569` | 96 | 536 | 55 | 22/21 | 18 | 31 | 29 | 0 |
| DE | `bf8bbf70` | 102 | 527 | 57 | 25/20 | 20 | 21 | 15 | 0 |
| KR | `a2cff6a9` | 108 | 630 (173) | 63 | 30/18 | 8 | 0 | 0 | 4 |
| GB | `413eea21` | 98 | 587 | 50 | 25/18 | 13 | 25 | 19 | 3 |
| ID | `f5992052` | 124 | 704 | 71 | 32/24 | 9 | 14 | 10 | 2 |
| SG | `a80e6c46` | 96 | 462 | 55 | 20/22 | 21 | 22 | 13 | 6 |
| SG #2 | `238c85ed` | 98 | 431 | 47 | 11/32 | 18 | 18 | 28 | 2 |
| KR #2 | `84de783e` | 102 | 318 | 57 | 13/32 | 2 | 0 | 8 | 2 |
| JP #2 | `de583439` | 117 | 426 | 60 | 25/28 | 11 | 3 | 5 | 2 |

**Knowledge base state after runs** (DB truth):

| Country | Scholarships | Providers live (merged) | Sources | Raw documents | Deadline states |
|---|---|---|---|---|---|
| DE | 26 | 26 (0) | 21 | 37 | unknown 19, expired 2, unclassified 5* |
| GB | 28 | 24 (1) | 14 | 44 | unknown 25, unclassified 3* |
| ID | 17 | 32 (1) | 10 | 24 | unknown 14, unclassified 3* |
| JP | 38 | 49 (2) | 34 | 68 | unknown 32, expired 2, unclassified 4* |
| KR | 0 | 39 (3) | 10 | 0 | — |
| SG | 40 | 27 (4) | 39 | 78 | unknown 40 |

\* unclassified = reference-seed manual rows (§7), created before the `deadline_state`
migration and kept visible by design (§17).

**Idempotency proof (second runs JP/KR/SG):** zero duplicate `scholarship.identity_key`
groups in all six countries; SG row count 22 → 40 only because run #2 discovered genuinely new
pages (28 merge events recorded as version rows, 0 duplicates); merge provenance rows exist
(DE 15, GB 19, ID 10, JP 42, SG 40); provider duplicates consolidated (`merged_into_provider_id`
set, e.g. SG 4 rows merged incl. NUSGS + DukeNUS → NUS).

**KR run 1 (pre-fix)** had failed on `provider_provider_code_key` UniqueViolation after 97
candidates — the root cause and fix are in §11/§28; the re-run above is the fixed engine.

---

*End of design document. Implementation stops here per program directive.*
