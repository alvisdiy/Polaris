# Public Launch Baseline Inventory

**Date:** 2026-11-19  
**Scope:** Milestone 0 baseline inventory plus subsequent test-isolation guard. Application source/config and this report changed only for the fail-closed test URL guard; no database rows, migrations, or Git state were intentionally changed.  
**Design:** `docs/superpowers/specs/2026-11-19-public-launch-recovery-design.md`  
**Plan:** `docs/superpowers/plans/2026-11-19-public-launch-baseline.md`

## Summary

The existing application and tests have a substantial working baseline, but release readiness is not established. Ruff, frontend tests, and Vite production build passed from their correct locations, with caveats below. Vue type checking currently fails because the existing `three` dependency has no declaration file. The Python suite was intentionally stopped at 16% after discovering local `.env` points to `localhost:5432/polaris`; `tests/conftest.py` creates tables and seeds registry records at startup. Because that database is not explicitly isolated for tests, it must not be run again against this URL. No additional database query was made. The test process may have created tables/seeded source rows before interruption; the exact partial side effects are unknown and should be checked by the owner before any cleanup.

Latest Git status confirms the working tree remains unusually large: 123 tracked paths modified/deleted and 311 untracked entries (the shell adapter summarizes/truncates individual paths, and Git's untracked count includes directory-level entries). Current checkout remains branch `develop`, HEAD `2e155446`; the full tracked/untracked path list was streamed to a grouped summary, not preserved verbatim. Three registered worktrees are present under `.claude/worktrees/`, each at `cd3a82c`; one is explicitly locked to a live Claude agent. Do not remove, unlock, or reuse any of them. Path-by-path ownership and complete inventory remain unresolved.

## Current verification

| Check | Result | Evidence / caveat |
|---|---|---|
| Ruff | **PASS on isolation changes** | `python -m ruff check database/config.py tests/conftest.py tests/unit/test_database_config.py` exited 0. Earlier full-repo Ruff run passed before these changes. |
| Frontend Vitest | **PASS** | Ran from `frontend/`: 3 files, 20 tests passed. |
| Vite production build | **PASS with warning** | Ran from `frontend/`; build exited 0. `three.module` chunk is 753.47 kB minified (192.66 kB gzip), above Vite's 500 kB warning threshold. |
| Vue typecheck | **FAIL** | `npx vue-tsc --noEmit` from `frontend/` fails at `src/components/HeroGlobe.vue(27,30)`: no declaration file for `three`. Do not add a dependency or declaration during this read-only milestone. |
| Python pytest | **Full suite blocked; focused guard tests pass** | Earlier full run `python -m pytest tests/ -q` began 2,037 tests and was stopped at 16%; `tests/conftest.py:39-46` may have created tables/seeded the local developer DB. After adding the fail-closed guard, `python -m pytest --noconftest tests/unit/test_database_config.py -q` passed 7 tests without shared DB fixtures. Full suite still requires an owner-provisioned disposable PostgreSQL target. |
| Database state | **Target identified, data not queried** | `.env` target metadata only: PostgreSQL at `localhost:5432`, database name `polaris`. Credentials were accidentally disclosed by a file read during diagnosis and are intentionally omitted here. No read-only database query was made. |
| Browser/runtime smoke | **Not re-run** | Historical audit evidence exists, but not treated as a current deployment result. |

The first two frontend command attempts were made from repository root, where no root `package.json` exists, and failed with npm `ENOENT`. They were corrected by setting the working directory to `frontend/`; the corrected tests and build passed. The Vue typecheck command is separate and failed as described above.

## Documentation versus executable evidence

- `docs/project-status.md` (snapshot dated 2026-11-09) describes prior discovery, review, test, and deployment checks. Counts and verification claims in it are historical, not current guarantees.
- `docs/PRODUCTION-READINESS.md` (dated 2026-11-09) documents a combined API + SPA Docker deployment and a checklist that still had production secrets, database, backup, TLS, and monitoring items unchecked. Its “infrastructure ready” summary should not be read as proof that a public deployment exists.
- The current target is Vercel frontend + Render API + separately managed PostgreSQL, which differs from the documented combined-container arrangement. No Vercel/Render service or public URL was verified in this milestone.
- `tests/conftest.py:39-50` performs `create_all()` and source-registry seeding at session startup. `tests/integration/test_aggregator_ingestion_isolated.py:25-27` requires a separate `POLARIS_AGGREGATOR_TEST_DATABASE_URL`; this is a significant guard for test target safety.
- Python package commands and pytest coverage floor are in `pyproject.toml`; CI at `.github/workflows/ci.yml` runs Ruff, unit tests, then full pytest with 85% coverage against a CI PostgreSQL service. CI does not run frontend tests, frontend build, or Vue typecheck in the checked workflow.
- `frontend/package.json` defines `test` and `build`, but not a `typecheck` script. `vue-tsc` is installed and the direct typecheck exposed the missing `three` types.
- `PRODUCT.md` exists and was preserved. It says the platform is a Vue/FastAPI/PostgreSQL web application, public scholarship browse/detail/recommendations and browser-local comparison/saved items, official-source provenance, and human review before publication. No edits were made to it.

## Change inventory status

The Git status adapter summarizes and truncates individual paths. Latest observed count is 123 tracked modified/deleted paths and 311 untracked entries; the complete raw path list was not retained, so the required path-by-path ownership inventory is **incomplete**. A safe grouped summary of entries showed:

- `api/`: 6 Python paths; `database/`: 22 Python paths.
- `configs/`: 13 JSON paths; `scripts/`: 80 paths; `services/`: 73 Python paths.
- `tests/`: 114 Python/JSON paths.
- `frontend/`: Vue, TS, CSS, HTML, and JSON files (52 grouped entries).
- `docs/`: Markdown, JSON, PNG assets; 53 grouped entries.
- Root/config artifacts include `.dockerignore`, Dockerfile/compose, `.env.example`, `pyproject.toml`, README, `PRODUCT.md`, local metrics/audit text and JSON, an untracked `polaris.db`, and `PHASE2_STATUS.md`.
- `.claude/worktrees/` contains three registered worktree directories. Their ownership/content is not fully inventoried; one is locked to an active agent. Preserve all.

Tracked changes span API, models/migrations, services, scripts/configs, frontend, tests, and docs. Untracked groups include code/docs/config, local database/artifacts, and worktrees. Do not infer generated/temporary status as permission to delete. No staging or commit was performed. Since individual paths and ownership remain unresolved, Stage 0 is not closed.

## Launch blockers and next steps

1. Capture and preserve the complete `git status --short --untracked-files=all` path list in a safe, unique report/notes location; classify every path and resolve ownership without touching or cleaning worktrees. The current tool adapter truncates output, so do not claim this inventory complete.
2. The pytest fallback guard is now implemented: under pytest, `database.config` does not load `.env`, and `get_database_url()` requires `POLARIS_TEST_DATABASE_URL` pointing to local PostgreSQL whose database name ends `_test` or `_scratch`. `.env.example` documents this variable. Seven focused tests passed via `--noconftest`; Ruff passed on touched Python files. Do not run the full suite until the owner provisions and confirms a disposable test DB. The interrupted run may have partially created tables or seeded source rows in local `polaris`; no cleanup was attempted.
3. Resolve the Three.js typing and bundle-size issues in a separately approved frontend milestone; inspect whether the globe is needed before retaining or removing the dependency. AntiSlop mode is AFTER: do not begin visual edits until the UI work is complete and audit it then.
4. Produce separate deployment and UI/catalog plans after the baseline inventory is complete. Verify hosting/provider facts before writing provider-specific deployment configuration.
5. Before production: establish managed PostgreSQL, backups and restore test, secret storage, explicit CORS origins, migrations reviewed against production schema, monitoring, and read-only deployment smoke checks.

## Safety statement

An earlier pytest command connected to the local PostgreSQL database because `python-dotenv` loaded `.env` when `database.config` was imported, despite `DATABASE_URL` being cleared from the process environment. The session fixture calls `Base.metadata.create_all()` and `seed_source_registry.seed_data()` before tests; pytest was stopped at 16%. Therefore schema creation and/or idempotent source-registry seeding may have changed the local `polaris` database. Exact effects are unknown; no rollback was issued because the test session may already have committed seed changes. A fail-closed pytest URL guard has since been added and focused guard tests passed without shared fixtures. No explicit database query, Alembic migration, discovery run, approval/rejection, Git staging, commit, push, reset, stash, clean, or deletion was performed during this recovery work. `PRODUCT.md` and existing design/project docs remain unchanged. Test/build tools may create ignored caches or generated frontend build output; those were not cleaned up.

`git diff --check` also reported a pre-existing trailing blank line at `.gitignore:65`, plus Windows LF-to-CRLF warnings on changed files. Neither was modified during this milestone.
