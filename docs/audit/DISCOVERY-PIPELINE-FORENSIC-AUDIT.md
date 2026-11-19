# POLARIS — SCHOLARSHIP DISCOVERY PIPELINE FORENSIC AUDIT

**Audit date:** 2026-10-04
**Branch/commit:** `develop` / `2e15544`
**Audit scope:** Read-only forensic trace of how Polaris discovers, classifies, extracts, curates and publishes scholarships. Inspected: `services/` (86 modules), `api/` (6 modules), `database/models/`, `scripts/` (63 files), `configs/countries/`, and the live PostgreSQL database (read-only queries only).
**Codebase state:** Current production implementation. No code, database, configuration, migration, test or frontend file was modified during this audit.

---

# 1. EXECUTIVE VERDICT

Polaris has a genuine, working discovery engine — but it is **not reachable from the application**. The API serves scholarships, recommendations and review only; there is no endpoint, scheduler or queue that triggers discovery or acquisition. Every discovery run in the database was started by a human running a script.

Discovery itself is real: a country run generates queries, calls Serper (Google), writes results into a bounded frontier, follows links from index pages to detail pages, and produces Scholarship rows. It is not seed-dependent — 0 of 4,760 frontier rows came from a seed or a known source. Over 10 completed runs it executed 1,039 search queries, fetched 559 pages, registered 131 verified sources and persisted 135 scholarships autonomously.

The binding constraints are downstream and operational, not algorithmic:
1. **No trigger.** Discovery runs only when someone runs `scripts/run_country_exploration.py`.
2. **Low yield.** 559 pages fetched across 10 runs → 135 records persisted → **40 approved**. 3,473 candidates are still pending, unprocessed.
3. **Two dormant paths.** The legacy `discover_scholarships_for_country` filters `status == "active"` (lowercase) while every writer uses `"Active"` — it sees 13 of 205 sources.
4. **18 of 40 approved records have `identity_key = NULL`**, so they are invisible to the deduplication index.

### Final classification

```text
SEMI_AUTOMATED_DISCOVERY
```

### Confidence

```text
HIGH
```

Verified from code and live database for every claim below. The only unverifiable item is §14's `exploration`-origin lineage: the database records the provenance label but no reverse foreign key links a Scholarship row back to the specific frontier candidate that produced it. This is stated as a break rather than asserted as working.

---

# 2. ACTUAL PRODUCTION DISCOVERY FLOW

```text
[scripts/run_country_exploration.py  ::  run_exploration()]
    ↓
[load_country_config(iso2)]                    configs/countries/<iso2>.json
    ↓
[create_search_provider()]                      env POLARIS_SEARCH_PROVIDER → serper
    ↓
[CountryExplorationEngine.run()]                services/exploration/engine.py:165
    ↓
[_seed_frontier(run_id)]                        engine.py:243
    ├── WebSearchSurface.execute()              surfaces/web_search.py:40
    ├── config.seed_urls (ALL EMPTY)            config_loader.py:57
    └── known SourceRegistry re-enqueue         engine.py:280
    ↓
[_frontier_loop(run_id, deadline)]              engine.py:310
    ↓
[claim_next(country_id)]                        frontier_repository.py:228
    ↓
[_process_candidate(candidate, run_id)]         engine.py:357
    ├── CandidateAnalyzer.analyze(url)          candidate_analyzer.py   (FETCH)
    ├── OpportunityClassifier.classify()        opportunity_classifier.py
    ├── ProviderResolver.resolve()              provider_resolver.py
    ├── AuthoritySourceResolver.resolve()       authority_source_resolver.py
    ├── VerificationEngine.verify_source()      verification_engine.py
    ├── _register_source() / _register_needs_review()   engine.py:550 / 644
    ├── AcquisitionService.acquire_from_source()      acquisition_service.py:87
    │       ├── connector.discover()            generic_playwright.py:176  (LINK FOLLOWING)
    │       ├── rank_candidate_urls()           acquisition_policy.py
    │       ├── _page_intent()                  page_intent.py
    │       ├── classify_listing_page()         listing_guard.py
    │       ├── run_pipeline()                  orchestrator.py:78
    │       └── _persist_with_dedup()           acquisition_service.py:373
    └── _expand_links()                         engine.py:759
    ↓
[FrontierRepository.upsert_candidate()]         frontier_repository.py:81
    ↓
[mark_done / mark_rejected / mark_failed_transient]  frontier_repository.py:276-297
```

| Step | Component | File | Function | Input | Output | DB Write? |
|---|---|---|---|---|---|---|
| 1 | Script entry | `scripts/run_country_exploration.py` | `run_exploration` | `--iso2` | engine + metrics | Yes (run row) |
| 2 | Config loader | `services/exploration/config_loader.py` | `load_country_config` | iso2 | `CountryExplorationConfig` | No |
| 3 | Search factory | `services/exploration/search/__init__.py` | `create_search_provider` | env | `SearchProvider` | No |
| 4 | Orchestrator | `services/exploration/engine.py` | `CountryExplorationEngine.run` | config | `ExplorationMetrics` | Yes |
| 5 | Discovery surface | `services/exploration/surfaces/web_search.py` | `WebSearchSurface.execute` | query plan | frontier candidates | **Yes** |
| 6 | Frontier store | `services/exploration/repositories/frontier_repository.py` | `upsert_candidate` | url, origin | `DiscoveryFrontier` | **Yes** |
| 7 | Claim | same | `claim_next` | country_id | candidate + lease | **Yes** |
| 8 | Fetch/analyze | `services/exploration/candidate_analyzer.py` | `CandidateAnalyzer.analyze` | url | `AnalyzedCandidate` | No |
| 9 | Classify (router) | `services/exploration/opportunity_classifier.py` | `OpportunityClassifier.classify` | analyzed | `ClassificationResult` | No |
| 10 | Provider | `services/exploration/provider_resolver.py` | `ProviderResolver.resolve` | org, url | `Provider` | **Yes** |
| 11 | Authority | `services/exploration/authority_source_resolver.py` | `AuthoritySourceResolver.resolve` | org, domain | candidates | No |
| 12 | Verify | `services/exploration/verification_engine.py` | `verify_source` | url + signals | verdict | No |
| 13 | Register source | `services/exploration/engine.py` | `_register_source` | url, verdict | `SourceRegistry` | **Yes** |
| 14 | Acquire | `services/exploration/acquisition_service.py` | `acquire_from_source` | `SourceRegistry` | `AcquisitionMetrics` | **Yes** |
| 15 | Link discovery | `services/ingestion/connectors/generic_playwright.py` | `discover` | entry url | `list[str]` | No |
| 16 | Page intent | `services/exploration/page_intent.py` | `classify_page_intent` | cleaned page | `PageIntentResult` | No |
| 17 | Listing guard | `services/exploration/listing_guard.py` | `classify_listing_page` | cleaned + intent | `ListingGuardResult` | No |
| 18 | Extraction | `services/ingestion/orchestrator.py` | `run_pipeline` | document_id | `PipelineResult` | No |
| 19 | Extract client | `services/ingestion/real_extractor.py` | `DeterministicLLMClient.extract_scholarship` | clean text, url | `ExtractedDocument` | No |
| 20 | Persist + dedup | `services/exploration/acquisition_service.py` | `_persist_with_dedup` | extraction | `Scholarship` | **Yes** |
| 21 | Link expand | `services/exploration/engine.py` | `_expand_links` | analyzed.links | new candidates | **Yes** |
| 22 | Outcome | `services/exploration/repositories/frontier_repository.py` | `mark_done`/`mark_rejected` | outcome | state change | **Yes** |

---

# 3. DISCOVERY ENTRY POINT INVENTORY

| # | Entry Point | File | Function | Trigger | Environment | Production? | Writes DB? |
|---|---|---|---|---|---|---|---|
| 1 | Country exploration | `scripts/run_country_exploration.py` | `run_exploration` | CLI `--iso2` | SCRIPT_ONLY | No — manual | Yes |
| 2 | Global acquisition | `scripts/run_global_acquisition.py` | `main` | CLI | SCRIPT_ONLY | No — manual | Yes |
| 3 | Phase-3 frontier acquisition | `scripts/v01_phase3_acquire.py` | `run` | CLI | SCRIPT_ONLY | No — manual | Yes |
| 4 | Legacy scholarship discovery | `services/discovery/scholarship_discovery.py` | `discover_scholarships_for_country` | CLI | SCRIPT_ONLY | No — **broken filter** | No |
| 5 | MEXT pipeline | `scripts/run_mext_pipeline.py` | `main` | CLI | SCRIPT_ONLY | No — manual | Yes |
| 6 | Provider discovery | `scripts/run_provider_discovery.py` | `main` | CLI | SCRIPT_ONLY | No — manual | Yes |
| 7 | Country discovery orchestrator | `services/ingestion/country_orchestrator.py` | `CountryDiscoveryOrchestrator.discover_all_sources` | library | SECONDARY_PRODUCTION | No caller in `api/` | Yes |
| 8 | Ingestion discovery | `services/ingestion/discovery.py` | `DiscoveryOrchestrator` | library | SECONDARY_PRODUCTION | No caller in `api/` | Yes |
| 9 | Source registration | `services/discovery/source_registration.py` | `register_source` | library | SECONDARY_PRODUCTION | No caller in `api/` | Yes |
| 10 | Ecosystem discovery | `services/ingestion/ecosystem_discovery.py` | module | library | SECONDARY_PRODUCTION | Not traced to a live caller | Yes |
| 11 | Country coverage | `services/ingestion/country_coverage_orchestrator.py` | module | library | SECONDARY_PRODUCTION | Not traced to a live caller | Yes |
| 12 | Seed scripts (sources) | `scripts/seed_source_registry.py` | `main` | CLI | SCRIPT_ONLY | No | Yes |
| 13 | Seed scripts (awards) | `scripts/seed_manual_scholarships.py` | `main` | CLI | SCRIPT_ONLY | No | Yes |
| 14 | **API surface** | `api/app.py` | — | HTTP | — | — | **No discovery endpoint exists** |

**API routers actually registered** (`api/app.py:112-114`): `recommendations`, `scholarships`, `review`. A search of `api/` for `explor|acquis|discovery|CountryExplorationEngine|AcquisitionService` returns **no functional references** — only prose in docstrings and schema descriptions.

### PRIMARY PRODUCTION ENTRY POINT

```text
File:    scripts/run_country_exploration.py
Function: run_exploration(iso2, dry_run, max_runtime)
Caller:  CLI (__main__ / argparse), human operator
Trigger: Manual command. No scheduler, no cron, no API route, no queue worker.
         Verified: grep for schedule|cron|APScheduler|BackgroundTasks across
         api/ and services/ returns no scheduling mechanism.
```

**SECONDARY_PRODUCTION:** `services/ingestion/country_orchestrator.py`, `services/ingestion/discovery.py`, `services/discovery/source_registration.py` — implemented and importable, but no production caller.

**SCRIPT_ONLY:** entries 1–6 and 12–13 above.

**TEST_ONLY:** `tests/` invokes the engine and acquisition service directly through fakes; these never run in production.

---

# 4. WHERE DOES THE FIRST URL COME FROM?

> If Scholarship, Frontier, RawDocument and SourceRegistry are empty, what creates the first candidate scholarship URL?

`CountryExplorationEngine.run()` → `_seed_frontier(run_id)` (`engine.py:243`) executes three sub-mechanisms:

**(a) Web search — the only one that produces URLs in practice.**
`QueryGenerator.generate_plan()` builds a query plan from the country config; `WebSearchSurface.execute()` issues it to `SearchProvider.search()` and writes each result through `frontier.upsert_candidate(...)` with `origin="web_search"`.

**(b) Config seed URLs — implemented, inert.**
`config.seed_urls` defaults to `[]` (`config_loader.py:57`). Verified across every country config on disk:

```
configs/countries/{au,cn,de,fr,gb,id,jp,kr,sg,us}.json  →  seed_urls: []  (all 10)
```

**(c) Known-source re-enqueue — implemented, produced nothing.**
`engine.py:280` re-enqueues up to 20 `SourceRegistry` rows per run as `origin=CandidateOrigin.KNOWN_SOURCE`. This cannot contribute to an empty-database start by definition.

**Database proof** that (a) is the live mechanism — frontier rows by origin:

| origin | rows |
|---|---|
| `web_search` | **595** |
| `link_expansion` | **4,165** |
| `seed` | **0** |
| `known_source` | **0** |
| `batch_import` | **0** |

| Mechanism | Implemented? | Production? | First URL generated? | Evidence |
|---|---|---|---|---|
| Manual seed | Yes | No | **No** — `seed_urls: []` in all 10 configs; 0 `seed` rows | `config_loader.py:57`, live config files |
| Country exploration | Yes | Script-triggered | **Yes** | `engine.py:165`, 10 completed `exploration_run` rows |
| Source Registry | Yes | Yes, downstream | No — requires rows to exist first | `engine.py:280` |
| Provider discovery | Yes | Script-only | No — resolves providers *from* candidates | `provider_resolver.py` |
| Search engine | **Yes** | **Yes** | **YES — this is the mechanism** | `surfaces/web_search.py:88`, 595 rows, 1,039 queries over 10 runs |
| Sitemap | No | No | No | No sitemap parser exists anywhere in `services/` |
| HTML link following | **Yes** | Yes | No — second-order | `engine.py:759` `_expand_links`, 4,165 rows |
| Connector discovery | **Yes** | Yes | No — requires a source entry URL | `generic_playwright.py:176`, called at `acquisition_service.py:139` |
| Frontier expansion | **Yes** | Yes | No — second-order | `frontier_repository.py:81` |

```text
FIRST_URL_SOURCE:
SerperSearchProvider — a Google-backed web search executed by
WebSearchSurface.execute(), writing results into discovery_frontier
with origin='web_search'
```

This requires `POLARIS_SERPER_API_KEY`. Without it the surface degrades
(`web_search.py:57` sets `degraded_reason`), `seed_urls` is empty and
`known_source` needs pre-existing rows — so with the key absent and an empty
database, **no URL is created at all**.

---

# 5. COUNTRY → SCHOLARSHIP FLOW

```text
Country (iso2)
 ↓
RunRepository.start_run()                    exploration_run row
 ↓
load_country_config(iso2)                    configs/countries/<iso2>.json
 ↓
QueryGenerator.generate_plan()                query_generation.py
 ↓
WebSearchSurface.execute()                   ── URL GENERATION HAPPENS HERE ──
 ↓
FrontierRepository.upsert_candidate()         discovery_frontier rows
 ↓
_frontier_loop → claim_next → _process_candidate
 ↓
CandidateAnalyzer.analyze()                  fetch page
 ↓
OpportunityClassifier.classify()             router, not gate
 ↓
VerificationEngine.verify_source()           → _register_source()
 ↓
AcquisitionService.acquire_from_source()     connector.discover() → rank → fetch → extract
 ↓
_persist_with_dedup()                        Scholarship (pending_review)
 ↓
ReviewService.approve()                      approved → public
```

| Stage | File | Function | Input | Output | Production? |
|---|---|---|---|---|---|
| Run creation | `exploration/repositories/run_repository.py` | `start_run` | country, config | `exploration_run` | Yes |
| Query plan | `exploration/query_generation.py` | `generate_plan` | config + offset | `list[PlannedQuery]` | Yes |
| **URL generation** | `exploration/surfaces/web_search.py` | `execute` | plan, country | frontier rows | Yes |
| Frontier insert | `exploration/repositories/frontier_repository.py` | `upsert_candidate` | url, origin | `DiscoveryFrontier` | Yes |
| Claim | same | `claim_next` | country_id | leased candidate | Yes |
| Fetch | `exploration/candidate_analyzer.py` | `analyze` | url | `AnalyzedCandidate` | Yes |
| Classify | `exploration/opportunity_classifier.py` | `classify` | analyzed | `ClassificationResult` | Yes |
| Verify source | `exploration/verification_engine.py` | `verify_source` | url + signals | verdict | Yes |
| Register | `exploration/engine.py` | `_register_source` | url, verdict | `SourceRegistry` | Yes |
| Acquire | `exploration/acquisition_service.py` | `acquire_from_source` | source | metrics | Yes |
| Expand | `exploration/engine.py` | `_expand_links` | analyzed.links | new candidates | Yes |

**Who creates `ExplorationRun`:** `RunRepository.start_run()`, called only from `CountryExplorationEngine.run()` (`engine.py:186`).

**Bounds that stop exploration** (`_frontier_loop`, `engine.py:310`):
`pages_processed < config.bounds.max_pages`, `time.monotonic() < deadline`
(`max_runtime_minutes`), no pending candidates, `claim_next()` returning `None`,
and `depth >= max_depth` in `_expand_links` plus a hard `added >= 15` per page.

**When no source is found:** the loop exits, the run is finished with whatever
status the metrics warrant. No error is raised.

### The three distinct things, not conflated

```text
COUNTRY_DISCOVERY     Finding candidate URLs about a country.
                      → WebSearchSurface. 595 rows, 1,039 queries.

SOURCE_DISCOVERY      Deciding which URLs are authoritative enough to be
                      registered as sources.
                      → OpportunityClassifier + VerificationEngine.
                        131 sources verified over 10 runs.

SCHOLARSHIP_DISCOVERY Turning a source into Scholarship rows.
                      → AcquisitionService + run_pipeline.
                        135 rows persisted over 10 runs.
```

All three are implemented and all three ran. They are separate stages with
separate funnels and separate failure modes.

---

# 6. SOURCE REGISTRY FLOW

```text
Candidate Source (frontier row, candidate_type='source')
 ↓
CandidateAnalyzer.analyze()              — fetch + parse
 ↓
OpportunityClassifier.classify()         — routing decision
 ↓
VerificationEngine.verify_source()       — VERIFIED | NEEDS_REVIEW | REJECTED
 ↓
_register_source() / _register_needs_review()
 ↓
SourceRegistry row
 ↓
_acquire_from_source()                   — acquisition_state
```

**States that actually exist** (`database/models/source_registry.py` +
`verification_engine.py`):

| Column | Observed values (live) |
|---|---|
| `status` | `'Active'` (189), `'active'` (13), `'Provisional'` (3) |
| `verification_state` | `'VERIFIED'` (139), `'NEEDS_REVIEW'` (31), `NULL` (35) |
| `acquisition_state` | `NULL` (193), `'no_scholarship_pages'` (11), `'acquired'` (1) |
| `page_type` | from `acquisition_policy.classify_page` |

| Transition | Function | File | Trigger | State Change |
|---|---|---|---|---|
| → VERIFIED | `_register_source` | `engine.py:550` | verdict == VERIFIED | insert or update |
| → NEEDS_REVIEW | `_register_needs_review` | `engine.py:644` | verdict == NEEDS_REVIEW | insert or update |
| → VERIFIED (existing) | `_apply_verification` | `engine.py:724` | `can_transition_to` permits | illegal moves refused |
| acquisition PENDING | `acquire_from_source` | `acquisition_service.py:134` | run start | increment attempts, timestamp |
| → ACQUIRED | `acquire_from_source` | `acquisition_service.py:292` | ≥1 extraction succeeded | `acquisition_state='acquired'` |
| → NO_SCHOLARSHIP_PAGES | `acquire_from_source` | `acquisition_service.py:167` | `ranked` empty | recorded with reason |
| → FAILED | `acquire_from_source` | `acquisition_service.py:149` | discover() raised, or all extractions failed | error string recorded |

> **Is SourceRegistry a source universe, an accumulated registry, or another structure?**

**An accumulated registry of URLs Polaris has encountered and judged
authoritative** — not a curated universe.

Evidence: `source_name` is populated as `(analyzed.title or url)[:255]`
(`engine.py:600`) — a page title, not a curated label. `discovered_via`
stores the frontier candidate, run, signals and page-type reasoning, i.e. the
row records *how it was found*, not that it was chosen. 35 rows have
`verification_state = NULL` (seeded, never through verification). 193 of 205
have `acquisition_state = NULL`, meaning they have never been acquired. The
registry is a byproduct of crawling, not a maintained list.

---

# 7. FRONTIER FORENSIC AUDIT

## 7.1 What one frontier row means

**One normalized URL that Polaris has decided is worth spending a fetch on,
scoped to exactly one country, carrying the evidence for why it was queued and
the outcome of what happened when it was processed.**

| Field | Meaning | Writer | Reader |
|---|---|---|---|
| `candidate_id` | Row identity (UUID) | DB default | ORM |
| `country_id` | Country scope; part of the dedup identity | `upsert_candidate` | claim, all queries |
| `url` | Normalized candidate URL | `upsert_candidate` | analyzer |
| `url_hash` | sha256 of normalized URL — **dedup identity with `country_id`** | `upsert_candidate` | `_existing_or_none` |
| `candidate_type` | `opportunity` \| `provider` \| `source` \| `unknown` | `upsert_candidate` | engine routing |
| `origin` | `web_search` \| `seed` \| `known_source` \| `link_expansion` \| `batch_import` | creator | audit |
| `origin_query` | The search query that produced it | `WebSearchSurface` | audit |
| `origin_url` | Parent URL for expansions | `_expand_links` | audit |
| `origin_source_id` | SourceRegistry link when known | `upsert_candidate` | engine |
| `depth` | Link hops from the seed candidate | `_expand_links` | depth bound |
| `priority` | Lower = processed first | creator | `claim_next` ordering |
| `state` | Lifecycle state (below) | `mark_*` methods | loop control |
| `retry_count` | Failed attempts so far | `mark_failed_transient` | retry decision |
| `next_retry_at` | Backoff gate | `mark_failed_transient` | `claim_next` |
| `lease_expires_at` | Claim lease; expiry frees the row | `claim_next` | reclaim |
| `evidence` | `{"observations": [...], "page_signals": {...}}` | `_merge_observation`, `record_page_signals` | audit |
| `outcome` | Classification, verification, authority, acquisition result | `_outcome` | audit |
| `run_id` | Which exploration run created it | `upsert_candidate` | run reporting |

**Identity:** `(country_id, url_hash)`. There is **no** `provider_id` or
`source_id` FK constraint on identity — `origin_source_id` is advisory only.
This is why 123 URLs are duplicated across countries (same international
programme, one row per country).

## 7.2 Frontier state machine

Actual state names (`database/models/discovery_frontier.py:19-27`):

```text
PENDING  ("pending")
    ↓  claim_next()
IN_PROGRESS  ("in_progress")
    ├── mark_done(candidate, outcome)          → DONE
    ├── mark_rejected(candidate, outcome)      → REJECTED
    ├── mark_deferred(candidate, outcome)      → DEFERRED
    └── mark_failed_transient(candidate, ...)  → PENDING (retry, next_retry_at set)
                                                or FAILED (retries exhausted)

DONE / DEFERRED  ── upsert_candidate with strictly lower priority ──→ PENDING
REJECTED         ── terminal. Never re-queued by upsert_candidate.
```

| From | To | Function | Condition | Reason |
|---|---|---|---|---|
| — | PENDING | `upsert_candidate` | new `(country_id, url_hash)` | first sighting |
| PENDING | IN_PROGRESS | `claim_next` | pending, not backed off, domain budget left | lease taken |
| IN_PROGRESS | DONE | `mark_done` | processed, outcome recorded | terminal success |
| IN_PROGRESS | REJECTED | `mark_rejected` | irrelevant page, job page, listing guard, permanent fetch error | evidence-backed verdict |
| IN_PROGRESS | DEFERRED | `mark_deferred` | retained low priority | not discarded |
| IN_PROGRESS | PENDING | `mark_failed_transient` | transient error, retries remain | `next_retry_at` backoff |
| IN_PROGRESS | FAILED | `mark_failed_transient` | retries exhausted | terminal failure |
| DONE/DEFERRED | PENDING | `upsert_candidate` | new evidence with lower priority number | re-analysis |

## 7.3 Frontier creators

| Creator | File | Function | What creates the URL? |
|---|---|---|---|
| Web search surface | `services/exploration/surfaces/web_search.py` | `execute` (line 88) | **Serper/Google result** |
| Config seeds | `services/exploration/engine.py` | `_seed_frontier` (line 262) | `config.seed_urls` — empty everywhere |
| Known sources | `services/exploration/engine.py` | `_seed_frontier` (line 294) | `SourceRegistry.crawl_entry_url` |
| Authority resolver | `services/exploration/engine.py` | `_process_candidate` (line 455) | Serper query for the official domain |
| Link expansion | `services/exploration/engine.py` | `_expand_links` (line 759) | **HTML `<a href>` on an analyzed page** |
| V0.1 hygiene script | `scripts/v01_frontier_hygiene.py` | — | rejects existing rows; creates none |
| Phase-3 script | `scripts/v01_phase3_acquire.py` | `_claim` | claims existing rows; creates none |

**Live distribution:** 4,760 rows — `link_expansion` 4,165 (87.5%),
`web_search` 595 (12.5%). By type: `source` 3,801, `opportunity` 779,
`provider` 180. By state: pending 3,473, rejected 710, done 561, failed 16.

---

# 8. INDEX → DETAIL LINK FOLLOWING

> Can the CURRENT PRODUCTION system discover a scholarship detail URL by following links from an index/listing page?

```text
YES
```

This is a **correction to prior documentation**, not a confirmation of it.

**Proof — path A, frontier expansion.** `_process_candidate` ends with
`_expand_links(candidate, analyzed, classification, run_id)` (`engine.py:759`)
*after* classification and source registration. It iterates `analyzed.links`,
filters by anchor text against configured scholarship/provider terminology
(or admits all links when the parent is `candidate_type == SOURCE`), and calls
`frontier.upsert_candidate(...)` with `origin=link_expansion` and `depth+1`.
Those rows are claimed on a later loop iteration and fetched.

Proof it runs: **4,165 `link_expansion` rows exist**, the largest origin class
by 7×, and `ExplorationMetrics.link_expansions` totalled **3,727** across the
10 recorded runs.

**Proof — path B, connector discovery inside acquisition.**
`AcquisitionService.acquire_from_source` (`acquisition_service.py:139`) calls
`candidate_urls = await connector.discover()` on the source's
`crawl_entry_url`, then `rank_candidate_urls(...)`, then fetches each ranked
page. `GenericPlaywrightConnector.discover()` (`generic_playwright.py:176`)
parses same-site links. This converts **source index page → detail pages →
Scholarship rows** without ever writing a frontier row for the detail page.

| Component | File | Function | Link Extraction | Creates Frontier? | Production? |
|---|---|---|---|---|---|
| Exploration link expansion | `services/exploration/engine.py` | `_expand_links` | Yes — `analyzed.links` | **Yes** | **Yes** |
| Acquisition connector discovery | `services/exploration/acquisition_service.py` | `acquire_from_source` → `connector.discover()` | Yes — same-site anchors | **No** (in-memory list only) | **Yes** |
| Legacy HTTP discovery | `services/discovery/scholarship_discovery.py` | `discover_scholarships_for_country` | Yes — `connector.discover()` | No | Script, and **broken** (§18) |

**Where path B's detail pages go:** they are fetched and extracted directly.
`_record_signals` is best-effort and only annotates a frontier row if one
already exists for that URL — so most detail pages acquired through path B
have **no frontier row at all**. This is the structural reason §14's lineage
breaks.

**Contradicted documentation:** `docs/progress/V0.1-SHIP-AUDIT.md:413-415`
states *"Index-page link following is not in the production path. Discovery
refuses to extract an index page but does not follow it."* Both production
paths above follow links. See §18.

---

# 9. CONNECTOR MATRIX

| Connector | Fetch | Discover | Follow Links | Playwright | SafeFetch | Robots | Production |
|---|---:|---:|---:|---:|---:|---:|---|
| `GenericPlaywrightConnector` | Yes | Yes | Yes | **Yes** | No — uses `url_safety` directly | Yes (`RobotsPolicy`) | **Yes — sole acquisition connector** |
| `GenericHTTPConnector` | Yes | Yes | Yes | No | **Yes** (`SafeFetch`) | Yes | No — legacy paths only |
| `MEXTConnector` | Yes | Yes | Yes | No | **Yes** (`SafeFetch`) | Yes | No — script/legacy only |
| `CountingSearchProvider` | n/a | n/a | n/a | No | n/a | n/a | Yes — search wrapper, not a crawler |

**Findings from implementation, not assumption:**

- **`AcquisitionService` hardcodes `GenericPlaywrightConnector`**
  (`acquisition_service.py:129`). `SourceRegistry.connector_name` is **ignored**
  on this path — it is only honoured by the legacy
  `_instantiate_connector(source.connector_name, ...)` dispatcher. So the
  `connector_name` column records an intent the production path never reads.
- **Playwright does not use `SafeFetch`.** It applies
  `validate_external_url` from `url_safety` and `RobotsPolicy`, but there is no
  `SafeFetch` wrapper (0 references in `generic_playwright.py`). SafeFetch's
  DNS-resolution re-check and redirect-chain enforcement apply to the HTTP
  connectors only.
- **`CandidateAnalyzer` is the production fetcher for the engine loop**, not a
  connector — it is a separate fetch path with its own timeout and
  per-domain delay, used before any connector exists.

---

# 10. PAGE PROCESSING DECISION TREE

Two classifiers act at different points and must not be conflated:

- **`OpportunityClassifier`** (`opportunity_classifier.py`) — routes frontier
  candidates during exploration. Labels include `SCHOLARSHIP`, `FELLOWSHIP`,
  `GRANT`, `STUDENT_FUNDING`, `JOB`, `VISA_JOB`. It is a **router, not a gate**.
- **`classify_page_intent`** (`page_intent.py`) — runs inside acquisition on
  the fetched page.

## 10.1 Exploration router (`_process_candidate`, `engine.py:390-420`)

```text
AnalyzedCandidate
     ↓
OpportunityClassifier.classify()
     ├── routing == "irrelevant"        → mark_rejected, RETURN (no expansion)
     ├── label in (JOB, VISA_JOB) AND routing == "reject"
     │                                   → mark_rejected, RETURN
     └── scholarship-family OR (review|low_priority AND type in opportunity/unknown)
             → provider resolution → authority → verify → register
             → acquisition → _expand_links → mark_done
```

## 10.2 Page intent inside acquisition (`acquisition_service.py:200-250`)

```text
RAW DOCUMENT
     ↓
classify_page_intent
     ├── SCHOLARSHIP_DETAIL → proceed to listing guard
     ├── UNKNOWN            → proceed to listing guard   (deliberate: see below)
     ├── SCHOLARSHIP_INDEX  → skip, pages_skipped_not_detail
     ├── SCHOLARSHIP_OVERVIEW → skip
     ├── PROVIDER_INFORMATION → skip
     ├── UNIVERSITY_INFORMATION → skip
     ├── APPLICATION_PORTAL → skip
     ├── NEWS_ANNOUNCEMENT → skip
     ├── FAQ → skip
     ├── GENERAL_PROGRAMME_PAGE → skip
     ├── IRRELEVANT → skip
```

**UNKNOWN is deliberately extracted.** `acquisition_service.py:205-210` states
UNKNOWN means "the classifier did not find enough evidence either way, not
that the page is known to be a list — and discarding those would throw away
real opportunities on a signal that is silent rather than negative." This is
correct for recall and is exactly the path the V0.1 `970,000 registrants`
failure travelled.

## 10.3 Listing guard (`listing_guard.py`, V0.1.1)

```text
PAGE INTENT (DETAIL or UNKNOWN only)
     ↓
classify_listing_page
     ├── HIGH_CONFIDENCE_LISTING → no extraction, no Scholarship row,
     │                             pages_skipped_listing, reason recorded
     │                             to evidence.page_signals.listing_guard
     ├── NOT_LISTING            → proceed to run_pipeline
     └── AMBIGUOUS              → proceed to run_pipeline  (NOT a rejection)
```

`AMBIGUOUS` behaving like `NOT_LISTING` is a deliberate recall trade, not an
oversight. One structural signal alone never blocks; `repeated_award_headings`
requires `programme_link_spike` to accompany it.

---

# 11. EXTRACTION PIPELINE

```text
RawDocument
 ↓
services.ingestion.cleaner.clean(LoadedDocument)      → CleanedDocument
 ↓
services.ingestion.extractor.extract(cleaned, client) → ExtractedDocument
 ↓
DeterministicLLMClient.extract_scholarship(...)        → ExtractedScholarship
 ↓
Pydantic validation (ExtractedScholarship, extra="forbid")
 ↓
validator.py / vocabulary control
 ↓
extraction_quality.py (name verdict, confidence)
 ↓
ScholarshipMapper.to_orm()  →  Scholarship(extraction_status="pending_review")
```

| Stage | File | Function | Responsibility | Output |
|---|---|---|---|---|
| Clean | `services/ingestion/cleaner.py` | `clean` | HTML → title/headings/anchors/text | `CleanedDocument` |
| Extract | `services/ingestion/extractor.py` | `extract` | Dispatch to client | `ExtractedDocument` |
| Client | `services/ingestion/real_extractor.py` | `DeterministicLLMClient.extract_scholarship` (line 861) | **Rule-based, not a language model** | `ExtractedScholarship` |
| Schema | `services/ingestion/extractor.py` | `ExtractedScholarship` | `extra="forbid"`, all fields nullable except `application_url`, `official_source` | validated model |
| Vocabulary | `services/ingestion/validator.py` | `validate_url`, validators | URL + controlled-vocabulary checks | corrections/None |
| Quality | `services/ingestion/extraction_quality.py` | name verdict / confidence | Is this name a scholarship name? | `extraction_meta` |
| Map | `services/scholarship/mapper.py` | `ScholarshipMapper.to_orm` (line 124) | Resolve provider/country/university, build children | transient `Scholarship` |

**`DeterministicLLMClient` is not an LLM.** Despite the `LLMClient` abstract
base and the `run_pipeline(..., llm_client)` signature, production wires
`DeterministicLLMClient` — pattern- and rule-based extraction. There is no
model call, no prompt, and no network dependency in extraction. The name is
inherited from an earlier design.

### Fields: extracted vs normalized/inferred

**Directly read from page content** (regex/marker extraction over cleaned text):
`scholarship_name`, `degree`, `funding_type`, `field_of_study`,
`application_url`, `official_source`, `timeline.*`, `eligibility.*`, `benefits.*`.

**Normalized or inferred by the extraction/mapping layer:**

| Field | How it is produced |
|---|---|
| `provider_name` | Extracted, then `_resolve_provider` falls back to the `SourceRegistry` row when absent |
| `country` | Extracted, then `_resolve_country` falls back to the source's country |
| `university` | Extracted, then `_resolve_university`; may stay NULL |
| `extraction_confidence` | Derived — the extractor's own confidence **in the name**, not in the record |
| `provenance_origin` | `meta.setdefault("origin", self.origin)` — written by the acquisition path, never by the page |
| `extraction_status` | Hard-coded `"pending_review"` in the mapper (`mapper.py:172`) |
| `identity_key` | Computed post-mapping (`acquisition_service.py:404`) |

`ExtractedScholarship` has **no** review or publication field by design
(`extra="forbid"`), documented at `extractor.py:65-68`.

---

# 12. SCHOLARSHIP CREATION + DEDUPLICATION

```text
ExtractedScholarship
 ↓
ScholarshipMapper.to_orm()          — provider / country / university resolution
 ↓     raises ValueError if the SourceRegistry row is missing → record dropped
 ↓
Scholarship(extraction_status="pending_review")     ← "it is a Scholarship" here
 ↓
scholarship_identity_key(provider_id, name, country_id)
 ↓
SELECT … WHERE identity_key = ?                     — application-level dedup
 ↓   found    → _merge_reacquisition(), returns None (duplicates_collapsed += 1)
 ↓   not found → session.add + flush
```

| Operation | File | Function | Identity Key / Rule | Result |
|---|---|---|---|---|
| Map | `services/scholarship/mapper.py` | `to_orm` | — | transient `Scholarship` |
| Identity compute | `services/exploration/acquisition_service.py` | `scholarship_identity_key` (line 34) | `sha256(provider_id \| lowercase(name) \| country_id)` | hex digest |
| Dedup lookup | `services/exploration/acquisition_service.py` | `_persist_with_dedup` (line 404-412) | exact `identity_key` equality | merge or insert |
| DB constraint | `database/models/scholarship.py:171` | `uq_scholarship_identity` | unique, **partial: `WHERE identity_key IS NOT NULL`** | IntegrityError on race |
| Plain save | `services/scholarship/repository.py` | `save` (line 23) | **none** | `add` + `commit` + `refresh` |

**`ScholarshipRepository.save` performs no deduplication at all.** It is the
function used by `persist_scholarship` (`orchestrator.py:110`). Only
`_persist_with_dedup` — the acquisition path — checks identity first.

### Explicit answers

**Same scholarship, different URL, different title, same provider, same country**
→ **TWO ROWS.** The key is `provider_id + normalized name + country_id`. A
different title hashes differently. The URL is not part of the key at all.
Confirmed live: `identity_key` is NULL on **18 of 40** approved rows, and
**135 rejected** rows also carry NULL identity — every row written by a seed
script or by `persist_scholarship` rather than `_persist_with_dedup`. The
partial unique index skips NULLs entirely, so **those rows are outside
deduplication**.

**Same scholarship, same URL, different extraction**
→ **ONE ROW, silently merged.** `_persist_with_dedup` finds the existing
identity and calls `_merge_reacquisition()`, which refreshes freshness and
provenance. The new extraction is **discarded** — nothing records that a
second, conflicting reading of the same page existed. 133 such merges occurred
across the 10 exploration runs (`duplicates_collapsed`).

**Same international scholarship discovered under multiple countries**
→ **N ROWS.** Frontier identity is `(country_id, url_hash)`, so one URL
produces one row per country. Scholarship identity includes `country_id`, so
the rows are distinct identities too. This is why 123 URLs appear duplicated
across countries.
---

# 13. REVIEW → PUBLICATION

```text
PENDING_REVIEW
 ↓
ReviewService.approve()          services/review/service.py:1112
 ├── APPROVED
 ├── REJECTED                     reject()          :1209
 └── NEEDS_CORRECTION             request_correction():1256
        ↓
      correct()  :1300  → requeue=True returns to pending_review
                       → requeue=False keeps prior state
 ↓
APPROVED
 ↓
published_filter()               services/review/publication.py:31
 ↓
Public API
```

| Step | File | Function | Gate |
|---|---|---|---|
| Queue read | `services/review/service.py:288` | `list_for_review` | None — reads unpublished rows deliberately |
| Approve | `services/review/service.py:1112` | `approve` | `evaluate_quality` → `NotPublishable` unless `override_quality` |
| Identity / official_source | `services/review/service.py` | `approve` | **Never overridable**, per M9 |
| Reject | `services/review/service.py:1209` | `reject` | Written reason required |
| Correct | `services/review/service.py:1300` | `correct` | Controlled vocabulary validated pre-write |
| Version | `services/review/service.py:981` | `write_version` | Every correction writes a version row |
| Audit action | `database/models/scholarship_review_action.py` | — | `ReviewActionType`, lowercase values |
| Publication predicate | `services/review/publication.py:31` | `published_filter` | `extraction_status == "approved"` |
| Public list | `services/scholarship/repository.py:69` | `get_all_approved` | `published_filter() AND NOT expired` |
| Public detail | `services/scholarship/repository.py:42` | `get_published_by_id` | `published_filter()` |
| Public search | `services/scholarship/repository.py` | `search_approved` | `published_filter()` |

**Who can approve:** any caller holding a `ReviewService`. There is **no
authentication or role check** in the service layer. The HTTP layer
(`api/routers/review.py`) is reachable without any visible auth dependency,
so the curation boundary is enforced by *convention and code discipline*
(writes go through `ReviewService`), not by an authorisation check.

**Four distinct stages, not three:**

```text
DISCOVERY    Finding URLs. engine.py:_seed_frontier, _expand_links.
             Produces frontier rows. No Scholarship rows.

ACQUISITION  Turning a source into candidate records.
             acquisition_service.py:acquire_from_source.
             Produces Scholarship rows in pending_review.

CURATION     Deciding what is true. ReviewService.approve/reject/correct.
             Changes review state, writes versions, provenance, audit actions.

PUBLICATION  Deciding what is visible. published_filter().
             A pure read predicate. No writer.
```

`persist_scholarship` writes `pending_review` and nothing else ever changes
`extraction_status` except `ReviewService` — verified by grep: no other module
assigns to `extraction_status`.

---

# 14. FIVE REAL SCHOLARSHIP LINEAGE TRACES

Selected across the three live provenance origins.

| Scholarship | Origin | Frontier | Source | Raw Document | Acquisition | Review | Public |
|---|---|---|---|---|---|---|---|
| Polytechnic Foundation Programme (PFP) | `exploration` | **BREAK** (below) | verified | 18 docs on source | exploration | 4 actions, 9 versions | Yes |
| Loughborough University Bursary | `exploration` | **BREAK** (below) | verified | 18 docs | exploration | 2 actions, 3 versions | Yes |
| SP Undergraduate Scholarship | `exploration` | **BREAK** (below) | verified | 15 docs | exploration | 3 actions, 4 versions | Yes |
| *(phase-3 record, e.g. Sheffield studentship)* | `phase3_acquisition` | yes — claimed from frontier | verified | yes | `v01_phase3_acquire.py` | approve action | Yes |
| Chevening ASEAN Scholarship | `unknown` (M8 seed) | **none** | yes | 0 docs | **none — hand-written row** | 2 actions (V0.1.2) | Yes |

**Live provenance distribution (all 202 rows):**

| `provenance_origin` | approved | rejected | pending | needs_correction |
|---|---:|---:|---:|---:|
| `exploration` | 9 | 13 | 0 | 1 |
| `phase3_acquisition` | 13 | 9 | 4 | 0 |
| `unknown` | 18 | 135 | 0 | 0 |

### Lineage breaks

```text
BREAK:  Scholarship → Frontier
REASON: No foreign key, and no column on `scholarship` records the
        frontier candidate that produced it. `provenance_origin` is a free-text
        label set by whichever path created the row
        (`acquisition_service.py:389`, meta.setdefault("origin", self.origin)).
        For the `exploration` path the row is created inside
        `_persist_with_dedup`, which knows only the RawDocument's source_id.
        For acquisition path B (connector.discover) the detail URL never had a
        frontier row at all.
EVIDENCE: database/models/scholarship.py — no candidate_id column;
          services/exploration/acquisition_service.py:373-425 — the dedup
          path takes only `document_id`.

BREAK:  Scholarship → Raw Document  (legacy seed rows)
REASON: 18 approved + 135 rejected rows carry `provenance_origin='unknown'`
        and were written by seed scripts, not by any fetch. They have a
        `source_id` but no document was ever stored for that page. Confirmed
        in the V0.1 Phase-2 work: every one of the 19 seed rows had a dead
        `official_page_url` and zero stored documents.
EVIDENCE: scripts/seed_manual_scholarships.py;
          live: those rows have source rows with 0 raw documents.
```

**What does hold:** every approved row has `source_id` non-NULL (0 with NULL),
and every scholarship row whose source exists joins to a `SourceRegistry` row.
14 approved rows draw from a source whose `verification_state` is not
`VERIFIED` — these are the V0.1 seed rows whose sources were never verified.

---


# 15. EMPTY-DATABASE TEST

## Scenario A

```text
Country exists
Scholarship = EMPTY
Frontier = EMPTY
SourceRegistry = EMPTY
RawDocument = EMPTY
```

**YES — conditionally.** The engine can bootstrap itself, but only via web
search:

1. `load_country_config(iso2)` → reads `configs/countries/jp.json` (present).
2. `create_search_provider()` → `SerperSearchProvider`; requires
   `POLARIS_SERPER_API_KEY`.
3. `QueryGenerator.generate_plan()` → ~12 queries per family.
4. `WebSearchSurface.execute()` → **first frontier rows created here**, origin
   `web_search`.
5. Loop → fetch → classify → verify → `_register_source()` → first
   `SourceRegistry` rows.

**If `POLARIS_SERPER_API_KEY` is absent:** the surface sets
`degraded_reason="search provider not configured"` and returns with zero
candidates; `seed_urls` is `[]` in all 10 configs; `known_source` needs
pre-existing sources. The loop finds nothing pending and exits. **The first
URL is never created.**

```text
ANSWER: YES, if and only if POLARIS_SERPER_API_KEY is set.
        NO without it.
```

## Scenario B

```text
Country exists
SourceRegistry = POPULATED
Frontier = EMPTY
Scholarship = EMPTY
```

**NO — not autonomously.** `_seed_frontier` re-enqueues up to 20 sources per
run as `known_source` candidates (`engine.py:280-300`), so a run *does* populate
the frontier from existing sources, and acquisition of a source requires the
frontier loop to reach that candidate. This works, and would be the bootstrap
path — but only if someone runs the engine.

```text
ANSWER: NO — works when a human invokes scripts/run_country_exploration.py.
```

## Scenario C

```text
Frontier = POPULATED
Scholarship = EMPTY
```

**YES.** This is the acquisition path in isolation and the most direct one.
Claim a candidate → resolve its source → `acquire_from_source` →
`connector.discover()` → `run_pipeline` → `_persist_with_dedup` → new
`Scholarship` in `pending_review`. `scripts/v01_phase3_acquire.py` demonstrates
exactly this end to end.

```text
ANSWER: YES
```

**Conclusion:** the engine's real entry condition is a **search provider key
plus a human running the script**. The frontier is a work queue, not a source
of URLs; it is filled by web search and link expansion, both of which require
a run to have been started.

---

# 16. DISCOVERY CAPABILITY MATRIX

| Capability | Status | Production? | Evidence |
|---|---|---|---|
| Country → Source | **FULL** | Yes (script-triggered) | `_seed_frontier` + verification + registration; 131 sources verified over 10 runs |
| Source → Candidate URL | **FULL** | Yes | `AcquisitionService.acquire_from_source` → `connector.discover()` → `rank_candidate_urls` |
| Index → Detail | **FULL** | Yes | `_expand_links` (4,165 rows) **and** `connector.discover()` |
| Provider → Scholarship | **PARTIAL** | Yes | `ProviderResolver` creates/resolves providers, but a provider row alone never drives a fetch; acquisition requires a `SourceRegistry` row |
| Search Engine → Scholarship | **FULL** | Yes | 1,039 queries, 1,191 results, 595 candidates, 135 scholarships persisted |
| Sitemap → Scholarship | **NOT_IMPLEMENTED** | — | No sitemap parser exists in `services/` |
| HTML Link → Scholarship | **FULL** | Yes | 4,165 `link_expansion` rows; 3,727 expansions across runs |
| Existing Frontier → Scholarship | **FULL** | Yes | `claim_next` → `_process_candidate` → acquisition |
| Manual URL → Scholarship | **PARTIAL** | Yes | Requires a `SourceRegistry` row; the legacy `discover_scholarships_for_country` that accepted loose URLs is broken (§18) |

---

# 17. DISCOVERY FUNNEL

Counts are live database readings and the summed `metrics` JSONB of the 10
`exploration_run` rows. No number here is estimated.

| Stage | Count | Source of Count | Reliably measurable? |
|---|---:|---|---|
| Countries configured | 10 | `configs/countries/*.json` | Yes |
| Exploration runs | 10 | `exploration_run` (all `completed`) | Yes |
| Search queries executed | 1,039 | Σ `metrics.queries_executed` | Yes |
| Search results received | 1,191 | Σ `metrics.search_results` | Yes |
| Frontier candidates created | 4,876 | Σ `metrics.candidates_created` | Yes |
| Frontier candidates in DB | 4,760 | `count(*) FROM discovery_frontier` | Yes |
| Dedup merges | 2,188 | Σ `metrics.dedup_merges` | Yes |
| Link expansions | 3,727 | Σ `metrics.link_expansions` | Yes |
| Pages fetched | 559 | Σ `metrics.pages_fetched` | Yes |
| Fetch failures | 154 | Σ `metrics.fetch_failures` | Yes |
| Sources verified | 131 | Σ `metrics.sources_verified` | Yes |
| Sources in registry | 205 | 139 VERIFIED / 31 NEEDS_REVIEW / 35 NULL | Yes |
| Sources acquired | 1 | `acquisition_state='acquired'` | Yes |
| Sources with no scholarship pages | 11 | `acquisition_state='no_scholarship_pages'` | Yes |
| Sources never attempted | 193 | `acquisition_state IS NULL` | Yes |
| Scholarships persisted (engine) | 135 | Σ `metrics.scholarships_persisted` | Yes |
| Duplicates collapsed | 133 | Σ `metrics.duplicates_collapsed` | Yes |
| Raw documents stored | 400 | `count(*) FROM raw_document` | Yes |
| Scholarship rows total | 202 | `count(*) FROM scholarship` | Yes |
| — rejected | 157 | `extraction_status` | Yes |
| — **approved** | **40** | `extraction_status` | Yes |
| — pending_review | 4 | `extraction_status` | Yes |
| Frontier still pending | 3,473 | `state='pending'` | Yes |

**Where the funnel is not measurable:**

```text
NOT MEASURABLE FROM CURRENT DATA
- Fetchable URLs: how many of the 3,473 pending candidates would actually
  return a page. Never measured; estimating it requires performing fetches,
  which this audit did not do.
- Detail pages: pages_fetched (559) is counted, but the DETAIL/UNKNOWN/INDEX
  split is not persisted per run. page_intent_counts exists on
  AcquisitionMetrics but is never written into exploration_run.metrics.
- Quality-passing candidates: the quality gate runs at review time, not at
  ingest, and its outcome is not stored as a countable event.
- Whole-corpus frontier→approved conversion is confounded: 18 approved and
  135 rejected rows predate the engine entirely (provenance_origin='unknown').
```

**Derived yield (arithmetic on measured values, stated as such):**
1,039 queries → 135 records persisted → 40 approved. **~26 search queries per
approved record.** Per run: 96–124 queries, 0–31 scholarships persisted —
about 4 approved records at best, ~2 typical.

---

# 18. DOCUMENTATION VS CODE

| Claim | Documentation | Actual Code | Status |
|---|---|---|---|
| "Index-page link following is not in the production path. Discovery refuses to extract an index page but does not follow it." | `docs/progress/V0.1-SHIP-AUDIT.md:413-415` | `_expand_links` (`engine.py:759`) creates frontier candidates from page links and runs in every production exploration run — 4,165 `link_expansion` rows, 3,727 measured expansions. `AcquisitionService` additionally calls `connector.discover()`. **Both follow links.** | **CONTRADICTED** |
| Same claim, earlier wording | `docs/progress/V0.1-PRODUCTION-CUT.md:473` | As above | **CONTRADICTED** |
| "This is the primary entry point for scholarship-first discovery." | `services/discovery/scholarship_discovery.py:117` | It filters `SourceRegistry.status == "active"` (lowercase, line 156). Every writer uses `"Active"`. Live: **13 rows match, of 205.** PostgreSQL `=` on `varchar` is case-sensitive. | **CONTRADICTED** |
| `raw_document.processing_status` implies document lifecycle tracking | Column exists, default `"pending"` | Only `services/ingestion/discovery.py:240` (legacy path) writes `"processed"`. The production path never updates it. **All 400 rows are still `pending`.** | **CONTRADICTED** |
| Extraction uses an `LLMClient` | `LLMClient` ABC, `run_pipeline(..., llm_client)` | Production wires `DeterministicLLMClient` — rule-based, no model call. The naming implies an LLM where there is none. | **CONTRADICTED** |
| "the ONE canonical orchestrator" | `services/exploration/engine.py:1` | `CountryExplorationEngine` is canonical for exploration, but `services/discovery/scholarship_discovery.py`, `services/ingestion/discovery.py` and `services/ingestion/country_orchestrator.py` form a second parallel discovery stack, still importable and still wired into two scripts. | **PARTIAL** |
| `SourceRegistry.connector_name` implies per-source connector selection | Column exists and is populated | `AcquisitionService` hardcodes `GenericPlaywrightConnector` (`acquisition_service.py:129`). Only the legacy dispatcher reads the column. | **PARTIAL** |
| "Query-driven strategy … a different mechanism from link-following." | `docs/progress/M11-DISCOVERY-ACQUISITION.md:490` | Both are implemented and both run in the same loop. They are distinct mechanisms, but both are production — not one being a script-only alternative. | **PARTIAL** |

Documentation was **not** modified. Reporting only.

---

# 19. TOP DISCOVERY BOTTLENECKS

Diagnosis only. No solutions proposed.

| Rank | Bottleneck | Evidence | Impact | Confidence |
|---|---|---|---|---|
| 1 | **No trigger.** Discovery is unreachable from the application | `api/app.py` registers only `recommendations`, `scholarships`, `review`. No scheduler/cron/queue in `api/` or `services/`. All 10 runs were manual script invocations. | **Severe.** The engine can work unattended for hours and will never be invoked. The catalogue grows only when a human remembers to run a command. | HIGH |
| 2 | **Fetched-page yield.** 559 pages → 135 records → 40 approved | Σ run metrics; live `extraction_status` counts | **High.** ~7.5% of fetched pages yield a record; ~30% of records are approved. Most loss is at curation, not ingestion. | HIGH |
| 3 | **Frontier backlog.** 3,473 pending, never processed | `state='pending'` | **High.** More candidates already exist than have ever been fetched. The constraint is processing throughput, not candidate supply. | HIGH |
| 4 | **Source acquisition barely runs.** 193 of 205 sources never attempted; 1 `acquired` | `acquisition_state` distribution | **High.** 131 verified sources were produced by exploration and then left unmined. The registry is far larger than what has been exploited. | HIGH |
| 5 | **Deduplication is opt-in and bypassed.** 153 rows have `identity_key = NULL` | NULL identity on 18 approved + 135 rejected | **Medium.** Those rows fall outside the partial unique index entirely. `ScholarshipRepository.save` performs no dedup check. | HIGH |

---

# 20. FINAL ANSWERS

### Q1 — How does Polaris currently find scholarships?

By asking Google. A country run generates ~12 queries per family from
`configs/countries/<iso2>.json`, sends them to Serper, writes the results into
a bounded per-country frontier, then crawls outward: it fetches each candidate,
classifies it, decides whether it is an authoritative source, registers it,
acquires scholarship links from it, and follows links found on every page it
touches, pushing each one back onto the frontier. That process — running only
when a human starts it — produced 22 of the 40 approved records. The other 18
were typed by hand into a seed script.

### Q2 — Where does the first scholarship URL come from?

`SerperSearchProvider.search()`, called by `WebSearchSurface.execute()`
(`services/exploration/surfaces/web_search.py:88`), written into
`discovery_frontier` with `origin='web_search'`. Requires
`POLARIS_SERPER_API_KEY`. Config `seed_urls` is empty in all 10 country
configs; `known_source` requires sources that already exist.

### Q3 — Does Polaris autonomously discover scholarship URLs?

**No.** The discovery *mechanism* is autonomous; the *invocation* is not.
There is no API endpoint, no scheduler, no queue worker. Nothing starts
discovery without a human running `scripts/run_country_exploration.py`.

### Q4 — Can Polaris discover scholarships from an index page in production?

**Yes**, by two independent production paths: `_expand_links` creates frontier
candidates from page links, and `AcquisitionService` calls
`connector.discover()` on each source's entry URL. Prior reports stating
otherwise are contradicted by the code — see §18.

### Q5 — What portion of the pipeline is discovery vs acquisition?

Not reliably expressible as a percentage. By code: discovery =
`_seed_frontier` + `_expand_links` — 2 of ~16 stages, but the stages that
generate 100% of URLs. By count: 4,760 of 4,760 frontier rows are discovery
output; 202 of 202 Scholarship rows are acquisition output.

### Q6 — What component turns the web into scholarship candidates?

`AcquisitionService.acquire_from_source`
(`services/exploration/acquisition_service.py:87`), via `run_pipeline` →
`DeterministicLLMClient` → `ScholarshipMapper.to_orm` → `_persist_with_dedup`.

### Q7 — What happens if all existing scholarship rows are deleted?

Every approved record disappears from the public API immediately; nothing
rebuilds them automatically. Re-running acquisition would repopulate
`pending_review` from the 3,473-row frontier backlog, but **nothing would
approve them** — curation is entirely manual through `ReviewService`. The 18
seed rows would be gone permanently, since they exist only as script literals.

### Q8 — What happens if the frontier is empty?

A new run still works, but only via web search. `_seed_frontier` creates fresh
`web_search` candidates; `seed_urls` contributes nothing (empty configs);
`known_source` re-enqueues existing sources if the registry is populated.
Without a Serper key, an empty frontier means an empty run.

### Q9 — What is the biggest discovery limitation?

**There is no trigger.** The engine is capable of unattended autonomous
discovery and has completed 10 runs — but nothing in the deployed application
ever invokes it. Every other gap here is smaller than the fact that a fully
automated pipeline is being driven by hand.

### Q10 — What is the single most important architectural fact revealed?

**Polaris has two parallel discovery stacks and no owner.** A modern,
canonical, web-search-driven engine (`CountryExplorationEngine`) exists and
works; alongside it a legacy stack (`services/discovery/scholarship_discovery.py`,
`services/ingestion/discovery.py`) is still importable, still wired into
scripts, and **silently broken** — its lowercase `status == "active"` filter
matches 13 of 205 sources. The live system's behaviour therefore depends on
which entry point an operator happens to run, and the broken one fails
*quietly*, returning an empty list rather than an error.

---

# 21. FINAL CLASSIFICATION

```text
SEMI_AUTOMATED_DISCOVERY
```

```text
WHY:
- Discovery is genuinely implemented, not stubbed: 1,039 search queries across
  10 completed runs produced 4,760 frontier candidates and 135 Scholarship
  rows with no manual URL entry beyond config seeds (which are empty).
- It is not AUTONOMOUS: no API route, scheduler or queue invokes discovery.
  All 10 runs were manual script executions.
- It is not ACQUISITION_ONLY: web search, query generation, provider
  resolution, authority resolution and link expansion all run in production.
- It is not SEED_DEPENDENT: 0 of 4,760 frontier rows came from a seed or a
  known source; 100% originated from web search (595) and link expansion
  (4,165).
- Human curation is the binding constraint on output, not URL supply:
  3,473 candidates remain unprocessed while 40 of 202 records are approved.

CONFIDENCE: HIGH
```

---

# 22. AUDIT ARTIFACTS

```text
FILES_INSPECTED:                 95+   (86 services, 6 api, models, scripts, configs)
FUNCTIONS_INSPECTED:             60+
DB_TABLES_INSPECTED:             10    (country, provider, source_registry,
                                        discovery_frontier, exploration_run,
                                        raw_document, scholarship,
                                        scholarship_version,
                                        scholarship_review_action, + joins)
ENTRY_POINTS_FOUND:              14
PRODUCTION_PATHS_FOUND:          1     (CountryExplorationEngine, script-triggered)
SCRIPT_ONLY_PATHS_FOUND:         9
DOCUMENTATION_CONTRADICTIONS:    5
UNRESOLVED_QUESTIONS:            4
```

**Unresolved questions**

1. **Frontier → Scholarship lineage is not reconstructable.** No FK and no
   column links a Scholarship row to the frontier candidate that produced it;
   `provenance_origin` is a free-text label. The 9 `exploration`-origin
   approved records cannot be traced to specific frontier rows after the fact.
   Determined as a break in §14; not resolvable from the current schema.
2. **Per-run page-intent outcomes are not persisted.** `page_intent_counts`
   exists on `AcquisitionMetrics` but is never written into
   `exploration_run.metrics`. The DETAIL/UNKNOWN/INDEX split for the 559
   fetched pages cannot be recovered from the database.
3. **`fetchable URLs` cannot be measured without fetching.** The 3,473 pending
   candidates are untested; nothing stored says which would resolve.
4. **The engine has never run against a `SourceRegistry` populated by anything
   other than exploration.** Seeded sources (13 rows, `status='active'`) have
   only ever been consumed by the broken legacy path, so Scenario B in §15 is
   reasoned from code, not observed.

---

# 23. NO IMPLEMENTATION PLAN

No V0.2 plan, refactor proposal, architecture recommendation, code change,
optimization plan or implementation prompt is provided. This document is the
forensic audit only.

The following were **found but deliberately left unfixed**, per the read-only
scope:

- The lowercase `status == "active"` filter in
  `services/discovery/scholarship_discovery.py:156`.
- `raw_document.processing_status` never advancing past `"pending"` on the
  production path (all 400 rows).
- `AcquisitionService` ignoring `SourceRegistry.connector_name`.
- 153 Scholarship rows with `identity_key = NULL`, outside deduplication.
- The contradicted link-following claims in the V0.1 reports.

Each is documented with evidence. None was modified, and no test, assertion or
lint suppression was touched to accommodate this audit.

