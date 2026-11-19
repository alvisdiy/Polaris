# Polaris Public Launch Recovery Design

**Date:** 2026-11-19  
**Status:** Proposed implementation sequence  
**Product record:** `PRODUCT.md` (existing; preserve and consult, do not replace)

## Goal

Bring Polaris to a credible public launch and portfolio presentation while preserving existing local work. A public visitor must be able to discover published scholarships, understand that facts come from official sources, inspect scholarship details, and use the supported comparison and recommendation flows. Deployment must be repeatable and must not expose operator controls or secrets.

## Verified baseline and uncertainty

The repository has a working Vue 3/Vite frontend, FastAPI API, PostgreSQL integration, discovery/ingestion and review workflows, and significant test coverage. The observed checks include a successful frontend production build and 1,906 passing / 131 skipped Python tests. The frontend build reports a 753 kB Three.js chunk; pytest reported three warnings.

The `develop` branch was observed three commits ahead of `origin/develop`, with 122 tracked files changed and hundreds of untracked entries (including two registered worktree directories). The existing worktree must be treated as valuable and not reset, cleaned, or broadly staged. Test and database counts from earlier audits are snapshots of that environment, not launch guarantees. No production hosting, domain, production database, backup/restore, or live deployment has yet been verified.

The current application is documented as deployable as a combined API + SPA container. The intended target is instead Vercel for the Vue frontend and Render for FastAPI, with PostgreSQL provisioned as a separate managed service. This requires explicit cross-origin API configuration and a production-safe migration plan. Provider-specific deploy behavior must be verified before claiming readiness.

## Product and implementation constraints

- `PRODUCT.md` and the existing PRD remain the product-truth sources; do not create competing product context or invent claims.
- Keep the current Vue 3 and FastAPI architecture. Do not migrate frameworks or introduce a new architectural layer just to refresh UI.
- Use Impeccable for relevant UI exploration/refinement and its quality checks. Use the existing design plugin tooling where applicable; follow an anti-slop bar: no generic template-driven redesign, arbitrary gradients/ornament, or animation without user value.
- Use Vue-compatible shadcn-vue components selectively only if the dependency and current structure support it; do not assume React shadcn components are drop-in Vue components. Three.js is not a component library; retain or remove it only based on a demonstrated product need and measured bundle impact.
- Official-source provenance, human review before publication, deterministic matching, truthful handling of unknown data, security, accessibility, and data integrity are non-negotiable.
- Preserve all pre-existing tracked and untracked work. Do not delete, reset, overwrite, or commit unrelated work. No production data mutation, migration, or discovery run without a reviewed target and explicit operational confirmation.

## Milestones

### 0. Establish a safe, reviewable baseline

Inventory changed and untracked files by coherent feature group, identify generated/local artifacts and worktree ownership, and map changes to the existing specs. Do not remove anything during inventory. Run safe checks against the intended checkout and distinguish current results from historical documents. Select the intended PostgreSQL target before running any command that could mutate data. Split the work into reviewable changes; do not commit until the exact contents are known and the user confirms when needed.

**Exit criteria:** an evidence-backed change inventory, a repeatable passing baseline (or explicit failure list), and no ambiguity about which checkout/database a later operation targets.

### 1. Deployment foundation: Vercel + Render

Configure frontend build/output and API base URL for Vercel; configure the FastAPI service, health checks, environment variables, and explicit allowed frontend origins for Render. Keep credentials only in provider secret settings. Confirm PostgreSQL connectivity and existing migration head. Define backups and restore verification before calling the database production-ready. Validate deploy configuration and smoke-test public routes plus protected admin routes without running discovery or mutating production records.

**Exit criteria:** preview deployment works end-to-end; health, public API, CORS, and admin-denial smoke checks pass; secrets are not in repository/build artifacts; migration and backup/restore procedures are documented and tested safely.

### 2. Public UX and visual quality

Audit the current product flows and visual system before editing. Use Impeccable for a scoped, evidence-based refinement of the existing Vue experience. Improve the primary path (discover → inspect source-backed details → compare/save or request deterministic recommendations), responsive behavior, accessible semantics, loading/empty/error states, and truthful treatment of missing or stale facts. Apply Vue-compatible components selectively. Avoid a wholesale redesign unless the UI audit demonstrates a concrete need and scope is agreed.

**Exit criteria:** the core flows work at desktop and mobile widths; keyboard and accessibility checks have no launch-blocking defects; browser verification covers real rendered routes; tests and production build pass; bundle warnings are either resolved or explicitly justified.

### 3. Catalog trust and public safeguards

Measure live-environment catalog quality without assuming historical counts. Verify the public API only exposes approved/actionable records, links lead to official evidence, and deadline/freshness/missing-data states are understandable. Improve data through the existing validated review/candidate-revision workflow; do not bulk approve, infer facts, or publish unreviewed extraction. Confirm admin authentication and operational limits are appropriate for public traffic.

**Exit criteria:** a documented, reproducible catalog-quality report; no known publication-boundary bypass; known limitations disclosed; any curated data changes have source evidence and review/audit history.

### 4. Release and portfolio handoff

Run the agreed test, lint, typecheck, build, deployment smoke, and security checks. Update the single current project-status/runbook entry with verified facts, deployment steps, recovery procedures, and open limitations; label older progress reports as historical rather than trying to rewrite every old report. Prepare a concise portfolio README with architecture, screenshots captured from the verified deployed UI, and honest product/data limitations.

**Exit criteria:** public URL verified, rollback/recovery documented, release checks recorded, portfolio materials match the actual shipped product, and unresolved risks are visible.

## Error handling and operational safety

- Deployment configuration failures must fail closed; missing admin credentials must not enable admin routes.
- Database migrations are reviewed and reversible where possible; take/verify a backup before production migration. Never auto-run ingestion/discovery as part of web service startup.
- Frontend should surface API unavailability and stale/unknown scholarship facts accurately, without fabricating fallback facts.
- Deployment smoke checks are read-only. Data-changing commands require an explicit target, dry-run/plan output where available, and approval before execution.
- Do not put tokens, database URLs, or private source credentials in docs, screenshots, logs, or frontend build variables.

## Verification strategy

Use the project’s pytest suite, frontend Vitest suite, Vue typecheck/build, Ruff, and current CI configuration. Add or update targeted tests only when a milestone exposes a gap. For UI changes, verify the rendered browser state at desktop and mobile sizes and use Impeccable’s applicable audit/finish workflow. For hosting, verify frontend-to-API CORS, `/health`, public endpoints, invalid admin credentials, and production environment separation. Report skipped tests and warnings rather than treating them as passes.

## Explicitly out of scope

- Migrating away from Vue or FastAPI.
- Replacing PostgreSQL or moving production records without a separate reviewed migration plan.
- Adding user accounts, reminders, OCR, or new opportunity types for the sake of launch.
- Increasing crawler/discovery volume before precision, review, and catalog-quality gates are met.
- Claiming global completeness or verified scholarship outcomes without evidence.
