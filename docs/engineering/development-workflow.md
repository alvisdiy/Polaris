# Development Workflow

**Purpose:** This document describes the end-to-end engineering lifecycle for Polaris. It maps the transition of a feature from an initial product requirements phase down to its implementation, validation, deployment, and maintenance.

---

## The Polaris Engineering Lifecycle

```
Idea / Feature Request
    │
    ▼
1. Documentation & Specs (PRD, ADR, Schema)
    │
    ▼
2. Definition of Ready (DoR Checklist)
    │
    ▼
3. Branching & Implementation (Incremental Commits)
    │
    ▼
4. Local Validation (Linting, Tests, Migration Checks)
    │
    ▼
5. Pull Request & Review (Checklists, PR Template)
    │
    ▼
6. Definition of Done (DoD Checklist)
    │
    ▼
7. Merge to Integration Branch (develop)
    │
    ▼
8. Release Preparation (release/ branch)
    │
    ▼
9. Deploy, Monitor & Maintain
```

---

## Workflow Steps

### Step 1 — Documentation & Specifications
Before writing any code, the feature is fully documented in `docs/v0.1/`. If the database is affected, the `database-schema-specification.md` and `data-dictionary.md` must be updated. If the architectural decisions change, a new Architecture Decision Record (ADR) must be created.

### Step 2 — Definition of Ready (DoR)
The task is reviewed against `docs/engineering/definition-of-ready.md`. If it satisfies all criteria (acceptance criteria defined, database schema documented, risks analyzed), the task is marked "Ready" and assigned to a developer.

### Step 3 — Branching & Implementation
The developer creates a feature branch off `develop` following `docs/engineering/branching-strategy.md`. Code is written incrementally. Commits follow the Conventional Commits specification.

### Step 4 — Local Validation
The developer runs the linting, formatting, and unit tests locally. Database migrations are verified by running `alembic upgrade` and `alembic downgrade` cycles.

### Step 5 — Pull Request & Review
The developer opens a PR targeting `develop` using `pull-request-template.md`. Another engineer reviews the PR using the rules in `code-review-checklist.md`.

### Step 6 — Definition of Done (DoD)
The developer and reviewer confirm the PR satisfies the **Definition of Done** checklist (`docs/engineering/definition-of-done.md`).

### Step 7 — Merge to Integration
The PR is squash-merged into `develop`. The feature branch is deleted.

### Step 8 — Release Preparation
Features on `develop` are bundled into a release branch, smoke-tested on staging, and merged into `main` with a release version tag (e.g., `v0.1.0`).

### Step 9 — Deployment & Monitoring
The container is deployed to production. Logs (handled by Loguru) are monitored for ingestion errors or database timeouts.

---

## Verification Checklist

- [ ] Feature maps to an existing specification.
- [ ] Developer confirmed the task was "Ready" before starting.
- [ ] Code successfully passed local verification.
- [ ] PR received approval from at least one peer.
- [ ] Release branch tested before merging to `main`.
- [ ] Production logs monitored after deployment.

---

## Examples

### Ingestion Pipeline Feature Lifecycle
1. Product requests MEXT crawlers.
2. Ingestion pipeline and connector specifications are created/updated.
3. Task is marked "Ready".
4. Developer branches `feature/mext-crawler` off `develop`.
5. Developer implements MEXT connector, formats code, and runs unit tests.
6. Developer opens PR, reviewer checks playbooks, and PR is merged.
7. Tag `v0.1.1` is released. Crawler is deployed and logs monitored.

---

## Anti-Patterns
- Skipping the documentation phase and implementing features based on verbal specifications.
- Bypassing the Pull Request review and merging code directly into `develop`.
- Failing to monitor logs after deployment to confirm the crawler runs successfully under network latency.

---

## References
- Definition of Ready: `docs/engineering/definition-of-ready.md`
- Definition of Done: `docs/engineering/definition-of-done.md`
- Branching strategy: `docs/engineering/branching-strategy.md`
- Code review checklist: `docs/engineering/code-review-checklist.md`
