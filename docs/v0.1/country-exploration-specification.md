# Country Exploration Specification

## Polaris — Scholarship Intelligence Platform

**Version:** 2.0
**Owner:** AlVis
**Status:** Canonical (implementation-accurate)
**Last Updated:** September 2026
**Supersedes:** provider-discovery-specification.md v1.0 (kept for historical reference; its surfaces/verification ideas are absorbed here)

---

# 1. Purpose

Country Exploration is the process by which Polaris starts with only a country
code (e.g. `JP`) and autonomously explores the open internet to discover the
country's scholarship ecosystem: opportunities, the organizations that offer
them, and the official sources that authoritatively describe them — then
verifies those sources, ingests scholarship information into the Knowledge
Base through the existing extraction pipeline, and expands discovery by
following outbound links, all within explicit bounds.

The engine must work with **zero pre-seeded providers and zero pre-registered
sources** for the country.

# 2. Scope

**In scope (v2):**
- `services/exploration/` — the Country Exploration Engine and all its components.
- `discovery_frontier` and `exploration_run` tables + repositories.
- `SearchProvider` abstraction with one real adapter (Serper) and a Null provider.
- Query generation from country configuration (JSON data files).
- Candidate analysis, opportunity classification, provider resolution,
  authority source resolution, verification.
- Integration with the existing acquisition/extraction/validation pipeline.
- Outbound link expansion, bounded iterative exploration.

**Out of scope:**
- Matching engine, API, frontend (unchanged).
- Multiple search provider adapters (interface is replaceable; one adapter ships).
- Open data / batch import surfaces (interface reserved, not implemented).
- Any provider-specific connector (MEXT connector is legacy, deprecated).

# 3. Product Principles

> **BROAD DISCOVERY → CAUTIOUS RESOLUTION → STRICT VERIFICATION**

1. **Discovery must be broad.** The discovery layer maximizes recall. It does
   not aggressively reject candidates because authority is unresolved, provider
   identity is unclear, classification confidence is low, or the page is an
   aggregator/blog/multilingual. Those conditions affect **priority, confidence,
   state, and routing** — not survival. A discovery candidate is only REJECTED
   with actual evidence of irrelevance (e.g. confidently a job/vacancy page).
2. **Resolution must be cautious.** Provider identity is resolved from multiple
   signals. Ambiguous identity → NEEDS_REVIEW. No auto-merging of uncertain
   organizations.
3. **Verification must be strict.** SourceRegistry and the Knowledge Base
   contain only accepted/verified authoritative knowledge. TLD and keyword
   matches are soft signals, never proof. Final states are explicit.

# 4. Discovery Page vs Authority Source

A search result or any discovered page is a **DISCOVERY PAGE** — evidence.
It is never automatically an **AUTHORITY SOURCE**.

```
DISCOVERY PAGE (aggregator / blog / directory / any site)
   → identify opportunity (name, aliases, deadlines mentioned)
   → identify provider (organization offering it)
   → discover official provider domain (targeted search)
   → discover official scholarship page
   → verify
   → ingest authoritative information
```

Discovery pages remain valuable provenance: they identify opportunity names,
providers, aliases, official links, related opportunities, and alternate
terminology. Both the discovery page and the authority source are preserved in
provenance. Aggregators are valid discovery evidence, not second-class data;
no specific website is hardcoded or treated as a dependency.

# 5. Country Exploration Lifecycle

One canonical loop in `CountryExplorationEngine` (`services/exploration/engine.py`):

```
1.  INITIALIZE RUN        exploration_run row (config snapshot, bounds)
2.  LOAD COUNTRY CONFIG   configs/countries/{iso2}.json
3.  GENERATE QUERIES      QueryGenerator → bounded query plan
4.  EXECUTE SURFACES      WebSearchSurface (queries → search → candidates)
                          seed_urls from config
                          KnownSourceSurface (existing verified sources)
5.  PERSIST CANDIDATES    frontier upsert with evidence merge

    FRONTIER LOOP (bounded):
6.  CLAIM                 FOR UPDATE SKIP LOCKED + lease
7.  FETCH / ANALYZE       CandidateAnalyzer (httpx → Playwright fallback)
8.  CLASSIFY              OpportunityClassifier → routing decision
9.  RESOLVE               ProviderResolver (opportunities/providers)
10. RESOLVE AUTHORITY     AuthoritySourceResolver → official domain/page
11. VERIFY                VerificationEngine → confidence + explicit state
12. REGISTER SOURCE       accepted → SourceRegistry (verification_state)
13. DISCOVER SCHOLARSHIPS verified source pages → scholarship URLs
14. ACQUIRE               fetch → RawDocument → cleaner → extractor →
                          validator → persist (existing pipeline, untouched)
15. EXPAND LINKS          outbound links → new frontier candidates (depth+1)
16. RECORD OUTCOME        outcome + evidence on the frontier row

    UNTIL frontier drained OR bounds reached

17. FINALIZE RUN          metrics, finished_at, report
```

Paths A (opportunity-first), B/C (provider-first), D (expansion-first) all
converge into steps 6–16. There are no other orchestrators.

# 6. Internet Discovery Architecture

Discovery surfaces generate frontier candidates:

| Surface | v2 status | Role |
|---|---|---|
| `WebSearchSurface` | implemented | Country → QueryGenerator → SearchProvider → candidates with full search provenance |
| `seed_urls` (config) | implemented | Config-listed entry URLs pushed as candidates (accelerator, optional) |
| `KnownSourceSurface` | implemented | Re-enqueues existing verified sources for refresh/expansion |
| `LinkExpansion` | implemented | In-loop step 15: outbound links of analyzed pages → frontier |
| Open data / batch import | reserved | Interface slots only; not implemented |

Candidate `candidate_type` hints at admission (OPPORTUNITY from
opportunity-family queries, PROVIDER from provider-family queries, SOURCE from
official-source queries, UNKNOWN otherwise). Hints are advisory; the
classifier decides after analysis.

# 7. SearchProvider Abstraction

```python
class SearchProvider(ABC):
    name: str
    async def search(self, query: SearchQuery) -> list[SearchResult]

# SearchQuery:  text, country_iso2, locale, gl, result_count
# SearchResult: url, title, snippet, position, provider_name
```

Implementations shipped:
- `SerperSearchProvider` — real adapter (Google via Serper.dev API). Endpoint,
  key (env `POLARIS_SERPER_API_KEY`), and result count configured via
  environment. httpx-based, no new dependency.
- `DDGSearchProvider` — free DuckDuckGo metasearch via the `ddgs` library
  (env `POLARIS_SEARCH_PROVIDER=ddgs`). No API key; the library is imported
  lazily behind one module-level seam, so it stays an optional dependency.
  Timeouts map to `TimeoutError`, other upstream errors (including "No
  results found." and rate limits) to `RuntimeError`, which the surface counts
  as failed queries. Upstream may throttle or block at any time — it is a
  best-effort backend, not a guaranteed one, and it never bypasses CAPTCHAs
  or access controls. Optional `DDGS_PROXY` env is honored by the library.
- `NullSearchProvider` — returns no results, records every query. Used in
  tests, `--dry-run`, and as safe fallback when no key is configured.

Selection: `POLARIS_SEARCH_PROVIDER` env var (default `serper`). Missing API
key ⇒ WebSearchSurface reports degraded; the run continues with seeds, known
sources, and link expansion. An unknown provider name fails fast with
`ValueError` rather than silently selecting another provider. The core engine
never knows which provider is active — it depends only on the interface.

**Query accounting:** the engine wraps the configured provider in
`CountingSearchProvider`, so every call — discovery queries and
authority-resolution queries alike — is counted at the provider boundary.
Per-call-site tallies drifted (the surface reported its own share only) and
made `queries_executed` disagree with what the backend was actually asked.

# 8. Query Generation

`QueryGenerator` is deterministic and configuration-driven. Country
configuration (JSON files under `configs/countries/`) supplies:

- `languages` — e.g. `["ja", "en"]` for JP
- `search_locale`, `search_gl` — search localization
- `terminology` — packs for `scholarship`, `education`, `provider`, `funding`
  (localized terms included in the same lists)
- `country_local` — native country name for localized queries (e.g. `"日本"`)

Four fixed query-family templates exist in code (not a DSL):

- **opportunity:** `"{scholarship} in {country} for international students"`,
  `"{funding} {scholarship} {country} {education}"`
- **provider:** `"{country} {provider} {scholarship}"`
- **official_source:** `"{country} {scholarship} official site"`
- **localized:** `"{country_local} {scholarship} {education}"` rendered per language

Terminology is substituted by random-but-seeded selection from the packs; the
plan is capped at `max_queries_per_run` (default 12) with per-run rotation so
successive runs explore new combinations. **No provider names appear in
configuration or code** — MEXT/JASSO/DAAD/GIST/CSC may only emerge as search
results. Each executed query carries `family` + text, recorded on every
candidate it produces.

# 9. DiscoveryFrontier

The persistent operational core: discovery work + provenance, not a URL queue.
A frontier row can answer: what was discovered, where, why, from which
country/query/surface, what type was inferred, what evidence supports it, what
happened when processed, and what it discovered next (via `origin_url_hash`).

```
discovery_frontier
  candidate_id       UUID PK
  country_id         UUID FK country NOT NULL
  url                TEXT NOT NULL          (normalized)
  url_hash           CHAR(64) NOT NULL      (sha256 of normalized URL)
  candidate_type     OPPORTUNITY|PROVIDER|SOURCE|UNKNOWN
  origin             WEB_SEARCH|SEED|KNOWN_SOURCE|LINK_EXPANSION|BATCH_IMPORT
  origin_query       TEXT NULL
  origin_url         TEXT NULL
  origin_url_hash    CHAR(64) NULL          (indexed; discovery-chain queries)
  origin_source_id   UUID NULL FK source_registry
  depth              INT DEFAULT 0
  priority           INT DEFAULT 5          (lower = processed first)
  state              PENDING|IN_PROGRESS|DONE|FAILED|REJECTED|DEFERRED
  retry_count        INT DEFAULT 0
  next_retry_at      TIMESTAMPTZ NULL
  lease_expires_at   TIMESTAMPTZ NULL
  evidence           JSONB                  (observations[] + page_signals)
  outcome            JSONB NULL             (label, routing, resolution, verify state)
  run_id             UUID NULL FK exploration_run
  created_at / updated_at / processed_at
  UNIQUE (country_id, url_hash)
```

**Evidence merge on dedup:** the UNIQUE constraint backstops an upsert that
APPENDS the new observation to `evidence.observations` and keeps the lowest
`priority` value (lower = processed first). The same URL discovered via Query
A, Query B, and official Page C keeps all three observations. Provenance
survives merges.

**Re-queue rule on merge:** merging can return an already-consumed candidate to
PENDING, but only when the new observation carries *strictly better* priority
than the row held before the merge. The previous value must be captured before
the merge updates it, otherwise the comparison is always false. `REJECTED` is
excluded: it is an evidence-backed verdict, and resurrecting it would spend
page budget re-judging pages already judged irrelevant. `DONE` and `DEFERRED`
remain re-queueable.

**Claiming:** `SELECT ... FOR UPDATE SKIP LOCKED` with `lease_expires_at`
leases; crashed workers' leases expire and rows are reclaimed automatically
(stale recovery). Retries use exponential backoff via `retry_count`/
`next_retry_at`; terminal after `max_retries`.

**Bounds enforcement (admission control):** per-country max candidates,
per-domain page caps, max depth; per-run budgets tracked in run metrics.

# 10. Candidate Lifecycle

States are explicit and auditable on the frontier row:

```
PENDING (DISCOVERED)
   → IN_PROGRESS (ANALYZING)
   → DONE (with outcome.classification.label + routing)
        or → FAILED (retries exhausted; backoff in between)
        or → REJECTED (clearly irrelevant: confident JOB/VISA_JOB,
                       error page, off-topic)
        or → DEFERRED (low-priority retention; not silently discarded)
```

Not every candidate passes through every state; transitions are recorded in
`outcome` with timestamps. `DONE`/`DEFERRED` can return to PENDING on strictly
better evidence (see the re-queue rule in §9); `REJECTED` and `FAILED` are
terminal for the run that set them.

Opportunity-level resolution lifecycle is tracked in outcome fields:

```
DISCOVERED → PROVIDER_IDENTIFIED → AUTHORITY_UNRESOLVED
           → AUTHORITY_CANDIDATES_FOUND → NEEDS_REVIEW → VERIFIED
or         → AUTHORITY_RESOLVED → VERIFIED
```

Authority resolution is never a hard discovery gate: an opportunity whose
official source cannot yet be found is persisted as AUTHORITY_UNRESOLVED /
NEEDS_REVIEW and can be retried in later runs.

# 11. Opportunity Classification

`OpportunityClassifier` is a multi-signal **router**, not an absolute gate.

Labels: `SCHOLARSHIP, FELLOWSHIP, GRANT, STUDENT_FUNDING, INTERNSHIP, JOB,
VISA_JOB, COURSE, OTHER, UNKNOWN`

Signals (weighted): title/headings/text term families (scholarship vs
fellowship vs grant vs job vs visa-job), URL path tokens (soft), search
snippet (when available), JSON-LD structured data (`JobPosting` → strong JOB
signal), organization context (employer vs educator), negative-context
handling (employment term families dominate when mixed with funding words).

Routing decision (confidence-aware):

| Outcome | Action |
|---|---|
| HIGH-confidence scholarship family | normal opportunity pipeline |
| MEDIUM-confidence scholarship family | opportunity pipeline at lower priority / further analysis |
| UNKNOWN | retain candidate, low priority / review queue — never silently discarded |
| AMBIGUOUS | retain as NEEDS_REVIEW / DEFERRED |
| HIGH-confidence JOB / VISA_JOB | reject from scholarship pipeline; evidence retained for audit |
| Clearly irrelevant | REJECTED |

The classifier answers "what should Polaris do with this candidate?" — not
"is this definitely a scholarship?".

# 12. Provider Resolution

Provider identity ≠ URL, and ≠ blind eTLD+1. `ProviderResolver` combines:

- registered domain (eTLD+1 via embedded public-suffix subset for target countries)
- normalized organization name (legal suffixes, casing, punctuation stripped)
- country scope
- page identity (title, org meta, JSON-LD `Organization`)
- official references / cross-links from verified sources

Decision model: strong match (same registered domain + country, or same
normalized name corroborated by official reference) → resolve to existing
Provider (upsert by `identity_key`), append observation to
`discovery_evidence`. Conflicting/insufficient evidence → new Provider with
`verification_status="needs_review"` — **never auto-merge ambiguous
organizations**. Existing verified providers are never downgraded.

Cardinality: **one Provider : N SourceRegistry rows** (a university can have
several official scholarship pages). Sources key on normalized URL.

# 13. Authority Source Resolution

Given an opportunity candidate with a provider: determine the official domain
and official scholarship page.

- Targeted discovery queries via the same `SearchProvider` interface:
  `"{org_name}" official`, `"{org_name} {scholarship_term}"` (bounded budget).
- Candidate official pages ranked by soft authority signals: HTTPS, country
  institutional domain patterns from config (`.go.jp`, `.ac.kr`, `.edu.cn` …
  — soft only), org-name↔domain consistency, page self-identification,
  references from already-verified sources.
- First result is NOT assumed official; institutional TLD is NOT assumed
  authoritative — those are ranking signals only.
- Output: AUTHORITY-SOURCE candidates (`SOURCE` type) into the frontier for
  verification; runner-ups preserved in evidence. If no official domain can
  be found: lifecycle state AUTHORITY_UNRESOLVED persisted, retryable later.
- Three outcomes are counted separately in run metrics: `authority_resolved`,
  `authority_candidates_found` (candidates scored below the resolve
  threshold), and `authority_unresolved` (no usable results). Counting only
  two of the three hid the middle case entirely.
- Resolution queries are issued through the engine's counting provider, so they
  are included in `queries_executed`.

# 14. Verification

`VerificationEngine` — the strict boundary. Combines evidence: HTTPS/TLS,
registered domain + country relation, organization identity match,
page self-identification, scholarship content presence, structured data,
official references, cross-links, references from verified sources.

- TLD and keyword signals are soft, weighted.
- Confidence ∈ [0,1] is used for routing only (HIGH → auto-verify if policy
  allows; MEDIUM → NEEDS_REVIEW; LOW → deferred/rejected per evidence).
- Final state is explicit and separate from confidence:
  `DISCOVERED / NEEDS_REVIEW / VERIFIED / REJECTED / DEPRECATED` — applied to
  Provider lifecycle and `source_registry.verification_state`.
- Never: ".ac.jp = automatically verified"; never "contains scholarship =
  official".

# 15. SourceRegistry Semantics

SourceRegistry is trusted/accepted knowledge — the accumulated result of
discovery + verification. It is NOT the discovery gate: discovery proceeds
whether or not the registry has entries for a country.

- Frontier may contain unlimited uncertain candidates.
- Registry entries carry `verification_state`
  (DISCOVERED / NEEDS_REVIEW / VERIFIED / REJECTED / DEPRECATED), `confidence`,
  and `discovered_via` provenance JSON.
- The registry is never weakened to inflate discovery volume. Only VERIFIED
  sources auto-feed acquisition; NEEDS_REVIEW sources require human approval
  (or a future policy change).

# 16. Scholarship Acquisition

The existing pipeline is reused untouched:

```
verified source entry page
  → scholarship URL discovery (connector.discover())
  → fetch → RawDocument (checksum dedup)
  → cleaner → extractor (DeterministicLLMClient) → validator
  → Scholarship persistence (Mapper/Repository)
```

`AcquisitionService` wraps this flow, taking sources/candidates from the
engine. Scholarship identity dedup: `scholarship.identity_key` =
sha256(provider_id + normalized name + country_id); the repository skips
insert when an identical identity_key exists — the same opportunity on 10
aggregators + 2 university pages + 1 government page produces ONE canonical
Scholarship with multiple provenance observations.

# 17. Link Expansion

Every analyzed page exposes outbound links (anchor text, title, context).
Expansion is prioritized, not blind: anchor text, page context, domain and
country relevance, scholarship terminology, organization identity, source
authority, candidate type. Qualified links are upserted to the frontier with
`origin=LINK_EXPANSION`, `depth=parent.depth+1`, `origin_url_hash=parent`,
full provenance, subject to `max_depth`, `max_pages_per_domain`, and per-run
expansion budget.

# 18. Bounds & Termination

Configured per country (with global defaults):
`max_depth` (3), `max_candidates` (2000), `max_pages` (300),
`max_pages_per_domain` (15), `max_runtime_minutes` (45), `max_retries` (3),
`per_domain_delay_ms` (1500), `max_queries_per_run` (12).

The run stops when: frontier drained, a bound is reached, run budget
exhausted, or repeated failures hit the retry limit. Runs are resumable:
frontier state persists; expired leases are reclaimed on the next run.

# 19. Retry / Resume Behavior

- Transient fetch errors (timeout/5xx/429) → exponential backoff
  (`retry_count`, `next_retry_at`).
- Permanent errors (404/410/robots-disallowed) → FAILED/REJECTED with reason.
- `IN_PROGRESS` rows with expired leases → reclaimed by the next run.
- Every retry and state transition recorded in `outcome.history`.

# 20. Idempotency

| Entity | Mechanism |
|---|---|
| Frontier candidate | UNIQUE(country_id, url_hash) upsert + evidence merge |
| Provider | upsert by identity_key; status never downgraded |
| Source | upsert by normalized official_url |
| Scholarship | identity_key + partial unique index; provenance observations accumulate |
| RawDocument | checksum dedup (existing, unchanged) |

A second full run of the same country creates no duplicate providers, sources,
or scholarships; frontier dedup merges evidence.

# 21. Provenance

Every artifact carries its discovery chain:

- Frontier: origin, origin_query, origin_url, origin_source_id, depth, run_id,
  evidence.observations[] (query, search provider, rank, snippet, anchor text).
- Provider: discovery_source/method/evidence + accumulated resolution
  observations.
- Source: `discovered_via` JSONB → frontier chain.
- Scholarship: source_id traceability + RawDocument linkage + run reference.
- Run: exploration_run row snapshots config + counters.

Any fact answers: which run, which query, which surface, which page.

# 22. Deduplication

- Frontier: evidence-merging upsert (above).
- Provider: multi-signal identity; NEEDS_REVIEW on ambiguity.
- Source: canonical URL normalization (lowercase host, strip fragments/tracking).
- Scholarship: identity_key dedup with multi-site provenance observations
  stored in scholarship version/metadata (discovery URLs recorded).

# 23. Coverage Metrics

Per-run metrics stored on `exploration_run.metrics` and printed by the report.
Field names as implemented:

| Field | Meaning |
|---|---|
| `queries_executed` | total search calls to the backend, counted at the provider boundary (discovery + authority resolution) |
| `discovery_queries` | the subset issued by the web-search surface |
| `queries_failed` | search calls that raised |
| `search_results` | organic results received by the discovery surface |
| `candidates_created` | frontier rows created this run (surface, seeds, known sources, authority, link expansion) |
| `candidates_by_origin`, `candidates_by_type` | rows created this run, read back from the frontier and grouped |
| `dedup_merges`, `pages_fetched`, `fetch_failures`, `retries` | frontier/loop activity |
| `classification_labels`, `jobs_rejected`, `opportunities_retained` | classifier outcome |
| `providers_created`, `providers_resolved`, `providers_needs_review` | provider resolution |
| `authority_resolved`, `authority_candidates_found`, `authority_unresolved` | authority resolution |
| `sources_verified`, `sources_needs_review` | verification |
| `scholarships_persisted`, `extraction_failures`, `duplicates_collapsed`, `link_expansions` | acquisition and expansion |
| `runtime_seconds`, `provenance_samples` | run envelope |

Invariant: `sum(candidates_by_origin.values())` equals `candidates_created`.
The distributions are derived from persisted rows rather than tallied at each
call site, which is what left them permanently empty in earlier reports and
what let `candidates_created` drift below the frontier row count.

Observed counts are reported, never asserted as acceptance thresholds.

# 24. Failure Modes

| Failure | Behavior |
|---|---|
| Search API missing/unreachable | WebSearchSurface degraded; run continues on seeds/known sources/expansion |
| Fetch failure (transient) | retry with backoff; FAILED after max_retries |
| Fetch failure (permanent) | FAILED/REJECTED with reason |
| Extraction failure | pending RawDocument retained; reprocessing preserved |
| Ambiguous provider identity | NEEDS_REVIEW (no auto-merge) |
| Authority unresolved | persisted as AUTHORITY_UNRESOLVED; retryable in later runs |
| Worker crash | lease expiry → automatic re-claim |
| DB failure | per-batch commits; savepoints for frontier batch inserts |

# 25. Security / Robots / Rate Limits

- `robots.txt` respected by the analyzer fetch layer (cached per domain).
- Identified User-Agent: `PolarisBot/0.2 (+https://polaris.example; discovery research)`.
- Per-domain delay (default 1500 ms), overall fetch rate limits, timeouts.
- API keys via environment only, never in code or DB.
- Official-source orientation: expansion prioritizes institutional domains,
  reducing aggressive crawling of unrelated sites.

# 26. Configuration

Country configuration is version-controlled JSON (data, not code, no config
table): `configs/countries/{iso2}.json` — languages, locale, terminology
packs, seed_urls (optional), bounds, rate limits, routing thresholds, soft
domain signals. Global defaults in `services/exploration/config_loader.py`.
Search provider selection via env: `POLARIS_SEARCH_PROVIDER`
(`serper` | `ddgs` | `null`), `POLARIS_SERPER_API_KEY` (serper only),
`DDGS_PROXY` (ddgs only, optional).

# 27. Testing Strategy

- Unit (no DB): QueryGenerator (families, localization, budget, rotation,
  no-provider-name assertion), classifier (all labels, multilingual,
  job/visa-job rejection, mixed-content dominance), provider resolver
  (variants merge, ambiguity → NEEDS_REVIEW, no downgrade), authority resolver
  (aggregator → official candidate), verification engine (soft signals,
  thresholds), search providers (Serper request shaping via mocked transport,
  Null provider recording).
- Integration (DB, fixtures): frontier repository (upsert merge, claim/lease,
  SKIP LOCKED, retries, stale recovery, bounds, re-queue rules), full mini-loop
  with a fake search provider + local HTML fixtures → opportunity retained,
  provider resolved, authority reached, jobs rejected, idempotency (second run
  creates no duplicates), bounded run, migration backfill correctness.
- **Isolation:** the engine commits (a run must be durable), so exploration
  integration tests bind their session to an outer transaction with
  `join_transaction_mode="create_savepoint"`, purge the country's frontier and
  run history inside it, and roll the whole thing back. Without this, one test
  run's committed rows changed the next run's numbers: the suite passed or
  failed depending on what an earlier run had left behind.
- Regression: existing matching/API suite stays green.
- No live internet in CI; live behavior behind manual E2E only.

# 28. Zero-Seed E2E

`python scripts/run_country_exploration.py JP --report` with zero JP sources,
zero providers, zero provider-specific connectors. Success = demonstrated
capability checklist (14 items: search executed, candidates created with
provenance, pages analyzed, scholarship/non-scholarship distinguished, ≥1
opportunity→provider→authority→verification chain, scholarship persisted
through the existing pipeline, provenance survives, expansion produces new
candidates, bounded run, idempotent second run). Counts reported as observed;
no specific provider required for success; no fabricated numbers.

**Prerequisites for a true zero-seed run:**

1. A configured `SearchProvider` — `POLARIS_SERPER_API_KEY` in the environment
   for serper, or `POLARIS_SEARCH_PROVIDER=ddgs` (no key needed). Without a
   working backend the run is *degraded*, not zero-seed: web discovery yields
   nothing and only the seeded known sources can be processed. A degraded run
   is not evidence of zero-seed capability and must be reported as such.
2. An empty frontier for the country. Leftover `REJECTED` rows are terminal
   (§9), so a country whose earlier runs condemned its known-source URLs will
   sit dormant until discovery supplies new URLs. Do not read that as a bug in
   the loop; inspect `queries_executed` and frontier states first.

`--dry-run` substitutes `NullSearchProvider` and therefore proves wiring, not
capability. It is never reported as an E2E pass.

# 29. Future Extensions

- Additional SearchProvider adapters (interface ready).
- OpenDataSurface, BatchImportSurface (interface slots reserved).
- LLM-assisted classification/extraction behind the existing LLMClient
  interface (DeterministicLLMClient is the current implementation).
- Authority-resolution retry scheduler (currently: next-run retry).
- Human review UI for NEEDS_REVIEW queues (states already persisted).
- Public-suffix list expansion beyond target countries.

# 30. Observed Zero-Seed Evidence (2026-09-26, Singapore)

Two live runs against a truly empty country (new `Country` row, new
`configs/countries/sg.json`, zero providers/sources/frontier), real Serper
search + real Playwright fetching, dev machine (not CI):

- **Run 1** (8-minute budget, `cad6827e`): 84 queries executed (12 discovery,
  0 failed), 119 search results, 447 candidates created (80 web_search /
  367 link_expansion; 307 source / 123 opportunity / 17 provider), 43 pages
  fetched (13 fetch failures), 25 sources verified, 24 providers created,
  67 scholarships persisted (34 duplicates collapsed). Classifications:
  36 SCHOLARSHIP / 3 JOB / 1 COURSE / 3 UNKNOWN. Authority outcomes:
  15 resolved / 21 candidates-only / 0 unresolved. Runtime 488s.
- **Run 2** (5-minute budget, on top of run 1): 60 queries, 197 new
  candidates (305 dedup merges into existing rows), 8 new sources verified,
  9 new scholarships (9 duplicates collapsed), status `completed`. No
  duplicate scholarship `identity_key` across runs. Totals after both runs:
  644 frontier rows, 32 providers, 33 sources, 76 scholarships,
  120 raw documents.

Bugs the first live execution exposed (all fixed, regression-tested):
acquisition called a non-existent `ScholarshipMapperWithIdentity` (every
extraction died before persistence); source registration collided on the
`crawl_entry_url` unique key — the pre-flight SELECT only matched
`official_url` — and the UniqueViolation poisoned the session so the
degradation handler crashed on a lazy `run.run_id` load; the CLI report
read detached ORM state after session close; `dedup_merges` was never
wired into the metrics snapshot.

Known limitations observed: providers were created from noisy org
identities (page footers such as `"-2021 © Myanmar Study Abroad"`);
US-based aggregators (finaid.org, UNCF) pass verification because soft
domain signals are TLD-based, so an out-of-country aggregator gate is
future work (§29); same-domain candidates produced near-duplicate provider
rows (3× `admissions.smu.edu.sg`), showing domain-level identity merging
needs to run across candidates, not only name matches.
