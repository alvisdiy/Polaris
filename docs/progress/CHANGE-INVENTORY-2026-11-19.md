# Change Inventory and Stage 0 Close-Out

**Date:** 2026-11-19
**Scope:** Read-only inventory of the current checkout. No file was staged, committed, deleted, renamed, or migrated. No database query, discovery run, or review action was performed.
**Supersedes:** blocker 1 ("capture and preserve the complete path list") in [PUBLIC-LAUNCH-BASELINE-2026-11-19.md](PUBLIC-LAUNCH-BASELINE-2026-11-19.md).
**Raw evidence:** [inventory-2026-11-19.txt](inventory-2026-11-19.txt), the unfiltered output of `git status --short --untracked-files=all` minus the inventory file itself.

## 1. Checkout identity

| Item | Value |
|---|---|
| Toplevel | `C:/data/AINGMAUNGG/Polaris` |
| Branch | `develop` |
| HEAD | `2e15544` |
| Upstream divergence | 0 behind, 3 ahead of `origin/develop` |
| Working tree | 437 entries: 119 modified, 4 deleted, 314 untracked |
| Tracked diff | 123 files, +7,604 / -2,412 |

The three unpushed commits are `2e15544`, `4e4751e`, and `2753c3f`.

## 2. Registered worktrees

Six worktrees are registered under `.claude/worktrees/`, all at `cd3a82c` on their own `worktree-agent-*` branch, each about 91 KB.

- Locked to a live Claude agent (PID 26292): `agent-a45ed9916e54ede16`, `agent-a9813aef290fed75a`, `agent-a9d80d11849d9a22a`, `agent-ad3a50940352c37d7`.
- Unlocked: `agent-a5c1e4a34ddfe1068`, `agent-aa4dc73932a64101e`.

None of them appears in the parent status output and none was opened, modified, removed, or unlocked. Ownership is unknown for the two unlocked ones; treat both as preserved work.

## 3. Classification

Every one of the 437 paths is assigned to one group. No path remains in "unknown".

| Group | Total | Modified | Deleted | Untracked | Contents | Action before commit |
|---|---:|---:|---:|---:|---|---|
| discovery-exploration | 128 | 44 | 0 | 84 | `services/exploration/`, `services/discovery/`, ecosystem and provider discovery, aggregator adapters, `configs/countries/*.json`, `configs/aggregators.json`, and 80 discovery scripts (`run_country_*`, `m10_*`, `m11_*`, `m91_*`, `p10_*`, `v01*`) | Review as one feature group. Scripts contain one-off audit/curation runners; split runnable tooling from historical one-offs. |
| tests | 114 | 27 | 0 | 87 | 52 unit, 43 integration, 9 api, 4 security, plus fixtures and golden data | Must ship with the code they cover. Security tests are part of the publication boundary and are untracked. |
| frontend | 60 | 6 | 4 | 50 | Vue views, components, stores, styles, API client, tests, plus `docs/design/DESIGN.md`, screenshots, and `docs/web-design.md` | The redesigned SPA is almost entirely untracked. Deleted `style.css` is replaced by `styles/base.css` and `styles/tokens.css`. |
| docs | 48 | 3 | 0 | 45 | Progress reports, ADR-015 to ADR-019, runbook, production readiness, audit reports, plus root `README.md`, `PRODUCT.md`, `PHASE2_STATUS.md` | Documentation for work not yet committed. Land alongside its feature group. |
| catalog-scholarship | 26 | 12 | 0 | 14 | `database/models/` core models, 10 new Alembic revisions, `services/scholarship/` identity, mapper, repository, freshness | Highest-risk group: 10 unreviewed migrations. Verify head and downgrade path before any commit. |
| ingestion-extraction | 14 | 10 | 0 | 4 | Cleaner, extractor, real extractor, validator, quality, robots, fetch safety, connectors | Ships with discovery work. |
| matching | 8 | 8 | 0 | 0 | Scoring, ranking, explanation, profile normalizer, service, orchestrator | Tracked and modified only. |
| local-artifacts | 8 | 0 | 0 | 8 | `polaris.db` (0 bytes), `_strings_dump.txt`, `_strings_audit_report.txt`, `mofa_view_759978.html` (120 KB), `p10_*.json`, `p11_*.json` | Local research output. Keep on disk, exclude from commits unless a metric file is cited by a report. |
| ops-deploy | 7 | 4 | 0 | 3 | `Dockerfile`, `docker-compose.yml`, `.dockerignore`, CI workflow, `pyproject.toml`, `.env.example`, `.gitignore` | Untracked Docker files are the documented combined-container deployment. Verify they match the new Vercel + Render target. |
| domain-vocabulary | 7 | 0 | 0 | 7 | `services/domain/` (degree levels, lifecycle, page labels, source trust, vocabulary, fallback) | New layer. Confirm it matches ADR-016 and ADR-018 before landing. |
| api | 6 | 4 | 0 | 2 | `api/app.py`, public routers and schemas, new `api/auth.py` and `api/routers/review.py` | Review router is what makes the documented 503/401 admin behavior real. |
| review-publication | 5 | 0 | 0 | 5 | `services/review/` (service, publication, quality, auto review) | Core publication boundary, entirely untracked. |
| **Total** | **437** | **119** | **4** | **314** | | |

## 4. Key finding

HEAD does not represent the running application. Most of the product described in `README.md` and `PRODUCT.md`, including review, discovery, domain vocabulary, the redesigned frontend, and 10 migrations, exists only as untracked files. Any deployment from HEAD would ship an older, smaller system, and any `git clean` or reset would destroy the current product.

That is why this milestone stops at inventory. The next step is not more code.

## 5. Stage 0 exit gate

| Criterion | Status | Evidence |
|---|---|---|
| Checkout and worktrees identified | Met | Section 1 and 2 |
| Every change accounted for by category | Met | Section 3, zero unknown paths |
| Unknown files preserved and called out | Met | Worktrees and local artifacts preserved, no cleanup |
| Safe checks current | Partially met | Baseline run: Ruff PASS, frontend Vitest PASS, Vite build PASS, Vue typecheck FAIL (`three` types), Python suite blocked by missing disposable DB |
| Database identity confirmed before any query | Met by not querying | No DB command was run in this milestone |
| Current evidence separated from historical docs | Met | Baseline report and this report label counts by date |

Blocker 1 from the baseline is closed. The remaining launch blockers are unchanged: disposable test database, `three` typing and bundle size, deployment topology, and production data safety.

## 6. Recommended next milestone

Land the existing work in reviewable commits, in this order, without changing behavior:

1. `ops-deploy` plus `.env.example` and `.gitignore`, so the tree has a buildable baseline.
2. `catalog-scholarship` migrations and models, one migration per commit, with `alembic upgrade head` and downgrade verified on a disposable database.
3. `domain-vocabulary`, `ingestion-extraction`, `matching`, `review-publication`, and `api`, each with its tests.
4. `discovery-exploration`, separating runnable scripts from one-off audit runners.
5. `frontend` plus `docs/design`, after the `three` typing issue is resolved or the globe is removed.
6. `docs` and status updates last, so reports describe committed code.

Commits are a separate, explicitly approved milestone: nothing was staged here.

## 7. Method and limits

- Commands used: `git rev-parse`, `git branch --show-current`, `git rev-list --left-right --count`, `git worktree list --porcelain`, `git status --short --untracked-files=all`, `git diff --stat`.
- The raw list was generated with Git itself, not a shell truncation, so all 437 paths are present in `inventory-2026-11-19.txt`.
- Group classification is path-based. It states what a file belongs to, not who wrote it or whether it is finished. Per-file review is still required before staging.
- `git diff --check` was not run on this file because it is untracked and has no index entry.
