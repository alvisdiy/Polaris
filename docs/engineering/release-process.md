# Release Process

**Purpose:** This document defines the release lifecycle for Polaris. It outlines how development code is stabilized, packaged, deployed, tagged, and rolled back in production.

---

## Release Lifecycle

```
develop ──> release/vX.Y.Z ──> main (tagged vX.Y.Z)
              │                    │
              ├── QA Testing       ├── Deployment to Production
              └── Bug Fixing       └── Rollback if failures occur
```

---

## Step-by-step Process

### Step 1 — Freeze and Branch
When milestones for a release are complete on `develop`:
1. Create a release branch off `develop`:
```bash
git checkout -b release/v0.1.0
```
2. Increment the version number in `pyproject.toml` (or config file).

### Step 2 — QA and Verification
Run the verification suite:
1. Ensure all tests pass: `pytest`
2. Run database migration tests: verify `alembic upgrade head && alembic downgrade` cycles.
3. Deploy to the staging environment.
4. Perform smoke tests on API endpoints and pipeline steps.

### Step 3 — Merge and Tag
Once staging tests pass:
1. Merge the release branch into `main` using a merge commit (do NOT squash):
```bash
git checkout main
git merge --no-ff release/v0.1.0
```
2. Tag the merge commit on `main` following Semantic Versioning rules:
```bash
git tag -a v0.1.0 -m "Release version 0.1.0"
git push origin main --tags
```
3. Merge the release branch back into `develop` to ensure version bumps and bug fixes are synced:
```bash
git checkout develop
git merge --no-ff release/v0.1.0
git branch -d release/v0.1.0
```

### Step 4 — Deployment
Deploy the tagged version (`v0.1.0`) to production using the containerized Docker stack.

---

## Versioning Rules (SemVer)

Given a version number `MAJOR.MINOR.PATCH`, increment the:
- **MAJOR** version when you make incompatible API changes.
- **MINOR** version when you add functionality in a backwards-compatible manner.
- **PATCH** version when you make backwards-compatible bug fixes.

---

## Rollback Procedure

If a critical failure occurs in production after a release:
1. **Identify the previous stable tag** (e.g., `v0.0.9`).
2. **Deploy the previous tag** immediately to restore service.
3. **Perform DB rollback** if the new release included migrations:
```bash
alembic downgrade <previous_revision_id>
```
4. Do NOT commit hotfixes directly to main to fix the release; deploy the rollback first, then fix on a `hotfix/` branch.

---

## Verification Checklist

- [ ] Version number bumped in `pyproject.toml`.
- [ ] No open blocker bugs exist on the release branch.
- [ ] Staging validation tests pass.
- [ ] Alembic migration upgrade/downgrade successfully tested.
- [ ] Release tag created on `main` and pushed.
- [ ] Release changes merged back to `develop`.

---

## Examples

### Major Release
- Feature: Added Exchange programs support to matching engine and schemas (violates old PRD version 0.1 scope).
- Version Bump: `v0.1.2` → `v1.0.0`

### Minor Release
- Feature: Added Playwright connector for oxford university.
- Version Bump: `v0.1.2` → `v0.2.0`

### Patch Release
- Fix: Corrected regex validation for IELTS overall scores in schemas.
- Version Bump: `v0.1.2` → `v0.1.3`

---

## Anti-Patterns
- Deploying untagged commits directly from `develop` to production.
- Skipping staging testing during patch releases.
- Deleting the release tag or rewriting history on `main`.
- Forgetting to merge release branch changes back into `develop`.

---

## References
- Branching strategy: `docs/engineering/branching-strategy.md`
- Definition of done: `docs/engineering/definition-of-done.md`
