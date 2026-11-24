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
| Backend full suite (migrated DB) | 1901 passed, 9 failed, 134 skipped |
| Coverage | 83.54% (CI gate is 85% — see blockers) |

The Docker Compose path was **not** verified in this run (no Docker in
the verification environment); PostgreSQL was installed natively instead.
Compose remains unverified until someone runs it from a clean machine.

## Known blockers and gaps

1. **Test setup is order-dependent (real bug).** `tests/conftest.py`
   creates tables with `Base.metadata.create_all`, which does not create
   the CHECK constraints added by Alembic migrations. The 5
   controlled-vocabulary DB-enforcement tests fail on a `create_all` DB
   and pass on a migrated DB. Test DBs should be built by running
   `alembic upgrade head`, in CI and locally.
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
