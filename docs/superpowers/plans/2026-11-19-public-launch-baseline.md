# Polaris Public-Launch Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a trustworthy, repeatable, read-only-verified baseline and complete inventory of Polaris's existing local work before deployment or product changes.

**Architecture:** This milestone does not change application architecture or data. It inspects the current checkout, worktrees, file changes, project instructions/specs, and safe verification commands, then records findings in one recovery report. All existing tracked and untracked content is preserved; no cleanup, staging, commit, migration, or data-writing command is allowed.

**Tech Stack:** Git on Windows, Python 3.11 + pytest/Ruff, Vue 3 + Vite/Vitest/Vue typecheck, PostgreSQL (read-only only if target identity is confirmed).

**Spec:** `docs/superpowers/specs/2026-11-19-public-launch-recovery-design.md`

## Global Constraints

- Preserve all pre-existing tracked and untracked work; do not delete, reset, overwrite, stash, clean, or broadly stage it.
- Do not commit or push. Do not apply migrations, seed data, run discovery, approve/reject records, or mutate any database.
- Do not print, copy into reports, or expose secrets; report only variable names and whether configured.
- Keep `PRODUCT.md`, existing project specs, and current architecture intact.
- Run checks only from the intended checkout and report failures, skips, and warnings accurately.
- No Vercel/Render deployment, provider authorization, or external publication in this milestone.

---

## File Map

- Create: `docs/progress/PUBLIC-LAUNCH-BASELINE-2026-11-19.md` — concise evidence-backed inventory, verification results, ambiguities, and next-milestone gates.
- Read only: `docs/project-status.md`, `docs/PRODUCTION-READINESS.md`, `docs/v0.1/PRD-v0.1.md`, `docs/v0.1/system-architecture-spesification.md`, `PRODUCT.md`, `.claude/CLAUDE.md`, root/frontend manifests, CI workflow, and relevant source/tests.
- Do not modify application, schema, migrations, frontend package manifests, lockfiles, provider settings, or existing historical reports in this milestone.

## Task 1: Capture checkout, branch, and worktree identity

**Files:**
- Read: Git metadata only
- Create/modify: none

- [ ] **Step 1: Record the exact checkout and branch**

Run from repository root:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git status --short --untracked-files=all
git log -5 --oneline --decorate
git branch -vv
git worktree list --porcelain
```

Do not pipe status through filters that hide paths. Save output to the task notes/report without including credentials.

- [ ] **Step 2: Reconcile each worktree path**

For every path in `git worktree list --porcelain`, inspect only its branch/HEAD/status:

```powershell
git -C "<worktree-path>" rev-parse --show-toplevel
git -C "<worktree-path>" status --short --untracked-files=all
git -C "<worktree-path>" log -1 --oneline --decorate
```

Do not remove or unlock worktrees. If a path is inaccessible or locked, record that fact and leave it unchanged.

- [ ] **Step 3: Summarize change scope without staging**

```powershell
git diff --stat
git diff --numstat
git diff --check
```

For untracked content, record paths and sizes from a bounded inventory, excluding `.git`, `.venv`, `node_modules`, `dist`, build output, and cache directories. Do not recursively dump generated directories. Do not call `git add`.

- [ ] **Step 4: Classify paths by intent**

Group paths into: backend/API, database/models/migrations, discovery/ingestion, frontend, tests, docs, config/ops, and generated/local/unknown. Mark uncertain ownership as **unknown**, not disposable. Identify overlapping concerns and any paths that must be reviewed before a later commit.

## Task 2: Reconcile implementation claims against current specs

**Files:**
- Read: spec and status documents listed in File Map
- Create/modify: none

- [ ] **Step 1: Build a claims matrix**

For each current project-status or production-readiness claim, record its source document/date, the relevant implementation/test anchor, and whether it is currently verified, historical-only, contradicted, or unknown. At minimum cover:

- Public routes and publication filtering.
- Admin authentication and failure-closed behavior.
- Review/audit/version workflow.
- Database migration head and clean-database setup.
- Discovery safety (registered sources, dry-run/scratch guards).
- Frontend routes and supported public workflows.
- CI test/lint/build commands.
- Current deployment assumptions versus requested Vercel + Render topology.

- [ ] **Step 2: Verify anchors without editing**

Use repository search and targeted reads to confirm referenced modules/tests exist. Do not infer current status from historical counts. If docs disagree with executable configuration or code, record the contradiction and cite both paths.

- [ ] **Step 3: List launch blockers separately from follow-up quality work**

Classify each issue as baseline safety, deployment, public UX/accessibility, catalog trust, or portfolio documentation. Do not expand scope into fixing any issue yet.

## Task 3: Re-run safe verification from the intended checkout

**Files:**
- Read: `pyproject.toml`, `.github/workflows/ci.yml`, `frontend/package.json`, frontend lockfile, `frontend/vite.config.ts`
- Create/modify: none (build output is permitted only if already ignored/generated and does not overwrite tracked user work)

- [ ] **Step 1: Confirm commands and target environment first**

Inspect manifests and CI to find actual lint, test, typecheck, and build commands. Check whether `.env` is present only as a boolean; never print values. Do not run commands that seed, migrate, ingest, or write to PostgreSQL.

- [ ] **Step 2: Run Python tests**

Use the project-configured test command, expected from current setup to be:

```powershell
$env:PYTHONPATH = "."
python -m pytest tests/ -q
```

Record exit code, passed/failed/skipped counts, warnings, duration, and whether any tests require external services. If database target cannot be confirmed or a test may mutate a non-test database, stop before that test and document the blocker.

- [ ] **Step 3: Run Ruff**

```powershell
python -m ruff check .
```

Record complete summary and exit code. Do not auto-fix.

- [ ] **Step 4: Run frontend tests and build**

From `frontend/`, run the package scripts:

```powershell
npm test
npm run build
```

Run Vue typecheck only if the installed project manifest/config defines a valid command; do not invent or add a script in this milestone. Record chunk warnings and generated output behavior. Do not modify dependencies or lockfiles.

- [ ] **Step 5: Compare current results to CI**

Read `.github/workflows/ci.yml` and report which exact checks CI runs and which local checks match. Do not claim CI passed based solely on local runs.

## Task 4: Record read-only database state only if safe

**Files:**
- Read: database configuration/session code and schema
- Create/modify: none (until identity and safe credentials are confirmed)

- [ ] **Step 1: Establish target identity without exposing the URL**

Determine whether runtime configuration points to a test, local development, scratch, staging, or production database using host/database name only; redact username, password, and query parameters. If identity is ambiguous, do not connect.

- [ ] **Step 2: Confirm connection is read-only before querying**

If and only if the target is explicitly identified as non-production or an explicitly authorized read-only production target, use a read-only transaction and query only schema revision plus aggregate counts needed for inventory. Do not select personal data, source credentials, tokens, or full scholarship text. Otherwise record “database state not rechecked; target identity unconfirmed.”

- [ ] **Step 3: Compare counts carefully**

Label all counts with environment and timestamp, and explicitly state they are snapshots. Do not mutate rows or run application scripts against the database.

## Task 5: Write and self-review the baseline report

**Files:**
- Create: `docs/progress/PUBLIC-LAUNCH-BASELINE-2026-11-19.md`

- [ ] **Step 1: Write the report from gathered evidence**

Include: current branch/commit divergence; worktree state; tracked/untracked path counts and categories; unknown/high-risk groups; spec-versus-implementation matrix; exact current test/lint/build results; database verification status; launch blockers; and a short recommended next milestone. Add paths and command names so another engineer can reproduce claims.

- [ ] **Step 2: Review for unsafe disclosure and overclaims**

Confirm the report contains no secret values, no unsupported “production ready” assertion, no historical count presented as current, and no instruction to delete/reset/stage broad path sets. Distinguish verified, historical, and unknown explicitly.

- [ ] **Step 3: Run report-only validation**

```powershell
git diff --check -- docs/progress/PUBLIC-LAUNCH-BASELINE-2026-11-19.md
git status --short --untracked-files=all
```

Confirm the only newly created source artifact is the report (plus any explicitly ignored build outputs created by tests). Do not stage or commit it in this milestone.

## Exit gate

Milestone 0 is complete only when:

- The intended checkout and all registered worktrees are identified, with any access/ownership uncertainty documented.
- Every existing change is accounted for by category; unknown files are preserved and called out.
- Current safe test/lint/frontend checks have results, or exact safety blockers are documented.
- Database identity is confirmed before any database check; otherwise no DB query was run.
- The baseline report distinguishes current evidence from historical documentation.

After this gate, prepare separate bounded plans for deployment, UI refinement, catalog trust, and release handoff. Do not implement those follow-on milestones as part of this plan.
