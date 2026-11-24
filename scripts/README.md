# Scripts inventory

`scripts/` grew by accretion: operational runners and one-off milestone
scripts live side by side with no marker telling them apart. This file is
that marker.

**Do not move or rename milestone scripts casually.** Some are referenced
by path from tests and audits (e.g. `tests/integration/test_direct_approval_guard.py`
names `scripts/m91_verify_vocabulary.py`, and `scripts/m10_bypass_audit.py`
carries a hard-coded list of script paths). Moving a script is a code
change, not a tidy-up, and needs its own test run.

## Operational — supported, keep working

These are the runners the README and runbook depend on.

| Script | Purpose |
|---|---|
| `pipeline_run.py` | Crawl → enrichment → deterministic review, one command |
| `run_country_exploration.py` | Country discovery (`--plan-only` / `--dry-run` / live, scratch DB only) |
| `run_country_coverage.py` | Country coverage orchestration |
| `run_country_crawl.py` | Country crawl runner |
| `run_global_acquisition.py` | Global acquisition run |
| `run_aggregator_discovery.py` | Aggregator radar run (own DB guard) |
| `harvest_aggregators.py` | Harvest aggregator feeds, register official URLs |
| `run_provider_discovery.py` | Provider discovery run |
| `run_mext_pipeline.py` | MEXT pipeline |
| `review_queue.py` | Operator review CLI (list / approve / reject via ReviewService) |
| `auto_review.py` | Deterministic auto-review used by the pipeline |
| `country_status.py` | Per-country catalogue status |
| `check_database.py` | Database sanity check |
| `seed_source_registry.py` | Seed the source registry (also used by tests) |
| `seed_provider_discovery_config.py` | Seed provider discovery config |
| `seed_manual_scholarships.py` | Seed manual scholarship records (pending review) |
| `register_source.py` | Register a source manually |
| `enrich_records.py` | Enrich existing records |
| `dev.mjs` | Root `npm run dev`: API + frontend together |
| `docker-entrypoint.sh` | Container start (migrations, then API) |

## Data fixes and imports — run once per data need, then keep

`apply_quarantine_manifest.py`, `backfill_degree_levels.py`,
`dev_raw_document.py`, `discover_china.py`, `discover_official_pages.py`,
`discover_providers.py`, `discover_providers_from_csv.py`,
`discover_scholarships.py`, `fix_provider_identity.py`,
`import_studyinjapan.py`, `run_cn_university_discovery.py`,
`ship_audit.py`, `validate_discovery_framework.py`

## Milestone one-offs — historical, candidates for archival

Written for a single milestone, audit, or curation pass. They document
what was done; nothing operational depends on running them again.
Prefixes: `m10_`, `m11_`, `m91_`, `p10_`, `v01_`, `v011_`, `v012_`, `v013_`.

That is 51 of the 84 scripts in this directory. Archiving them (to
`scripts/archive/`, with reference updates in tests) is a separate,
deliberate change — see `STATUS.md`.
