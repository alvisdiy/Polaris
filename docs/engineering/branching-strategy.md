# Branching Strategy

**Purpose:** This document defines the Git branching strategy and lifecycle rules for Polaris. It maintains stability on main branches while allowing parallel development in feature branches.

---

## Branch Structure

```
main (production-ready)
  ▲
  │ (release branch or tag merge)
develop (integration & active development)
  ▲
  ├─── feature/some-feature
  ├─── bugfix/some-bug
  ├─── refactor/clean-module
  └─── docs/update-docs
```

---

## Branch Types & Naming Conventions

| Branch Prefix | Source Branch | Target Branch | Purpose | Example |
|---|---|---|---|---|
| `main` | — | — | Stable production state. Only merged from `develop` or `hotfix/`. | `main` |
| `develop` | `main` | `main` | Integration branch for feature development. | `develop` |
| `feature/` | `develop` | `develop` | Implementing a new feature. | `feature/matching-ranking` |
| `bugfix/` | `develop` | `develop` | Fixing a bug found in development. | `bugfix/ielts-validation` |
| `hotfix/` | `main` | `main` & `develop` | Urgent production fix. | `hotfix/expired-ssl` |
| `refactor/` | `develop` | `develop` | Restructuring code without behavior changes. | `refactor/connector-base` |
| `docs/` | `develop` | `develop` | Documentation-only updates. | `docs/acquisitions-update` |
| `release/` | `develop` | `main` & `develop` | Preparing for a new production release. | `release/v0.2.0` |

---

## Branch Lifecycle & Merge Rules

### 1. Creating a Branch
- Always branch off the latest commit on `develop`.
- Perform a local pull before branching: `git pull origin develop`.

### 2. Commit Discipline
- Commit regularly in small, focused units (100–400 LOC).
- Follow Conventional Commits (see `commit-convention.md`).

### 3. Merging to `develop`
- Merging requires a Pull Request. Direct commits to `develop` are forbidden.
- The PR must satisfy the **Definition of Done**.
- At least one code review approval is required.
- Merge strategy: **Squash and Merge** (keeps the `develop` history clean and linear).

### 4. Merging to `main`
- Merges to `main` occur at release cycles.
- Merging is done via release branches (`release/vX.Y.Z`).
- A Git tag (e.g., `v0.1.0`) must be created on the merge commit on `main`.
- Merge strategy: **Create a Merge Commit** (preserves release branch context).

---

## Verification Checklist

- [ ] Branch branched off the latest `develop` commit.
- [ ] Prefix (`feature/`, `bugfix/`, etc.) is correct.
- [ ] PR is opened targeting the `develop` branch.
- [ ] No merge conflicts exist with target branch.
- [ ] All commits in the feature branch follow naming rules.

---

## Examples

### Good Branch Flow
1. Developer wants to add the university model.
2. Creates branch: `git checkout -b feature/university-model`.
3. Implements changes, tests, and commits.
4. Opens PR to `develop`.
5. PR gets squash-merged to `develop`.
6. Branch is deleted locally and remotely.

---

## Anti-Patterns
- Working directly on `main` or `develop`.
- Branching off another unmerged feature branch without explicit coordination.
- Long-lived feature branches that accumulate months of changes (merge features incrementally instead).
- Naming branches randomly (e.g., `alvis-fixes` or `new-db-stuff`).

---

## References
- Commit convention: `docs/engineering/commit-convention.md`
- Definition of Done: `docs/engineering/definition-of-done.md`
- Release process: `docs/engineering/release-process.md`
