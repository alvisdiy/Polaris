# How to Implement a New Feature

**Scope:** Step-by-step procedure for implementing any new feature in Polaris.

---

## Prerequisites

Before starting:

- [ ] Feature is defined in a spec document (`docs/v0.1/`)
- [ ] You have read the relevant spec completely
- [ ] You have reviewed the current codebase for related code

---

## Procedure

### Step 1 — Identify the Spec

Every feature traces to one or more spec documents:

| Feature Area | Spec Document |
|---|---|
| Scholarship data model | `database-schema-specification.md`, `data-dictionary.md` |
| Data ingestion | `knowledge-pipeline.md`, `connector-specification.md` |
| Source management | `source-registry-specification.md` |
| Matching/scoring | `matching-engine-design-specification.md` |
| AI explanations | `PRD-v0.1.md` §Feature 3 |
| API endpoints | `system-architecture-spesification.md` §2-3 |

If the feature is not covered by any spec, stop and raise the gap before implementing.

### Step 2 — Plan the Change

1. List every file that needs to be created or modified.
2. Identify which layer each change belongs to:
   - **Model** — `database/models/`
   - **Schema** — Pydantic schemas in the module
   - **Service** — Business logic in the module
   - **Route** — FastAPI endpoint in the module
   - **Migration** — `database/migrations/`
3. Identify dependencies between changes (models before services, services before routes).

### Step 3 — Implement Bottom-Up

Order of implementation:

```
1. Database model     → see commands/model.md
2. Pydantic schema    → see context/coding-standards.md
3. Service logic      → pure functions, injected dependencies
4. API route          → see commands/api.md
5. Migration          → see commands/migration.md
6. Tests              → see commands/tests.md
```

### Step 4 — Validate Against Spec

For each field/behavior:

- [ ] Field names match the Data Dictionary
- [ ] Types match the Data Dictionary
- [ ] Required/optional matches the spec
- [ ] Enum values match the defined enums
- [ ] Relationships match the schema spec

### Step 5 — Self-Review

Run through the checklist in `CLAUDE.md` → Review Checklist.

### Step 6 — Commit

One logical change per commit. Follow commit message format in `context/workflow.md`.

---

## Rules

- Implement only what the spec requires. No speculative features.
- If the spec is ambiguous, document the ambiguity and resolve before coding.
- Every model uses `TimestampMixin`.
- Every external input passes through Pydantic validation.
- Every new module has a clean `__init__.py` with public exports only.

---

## Anti-Patterns

- Starting code before reading the spec
- Implementing multiple unrelated features in one change
- Guessing field names or types instead of checking the Data Dictionary
- Adding dependencies not in the tech stack
- Skipping the self-review step

---

## References

- Coding standards: `.claude/context/coding-standards.md`
- Model conventions: `.claude/context/database.md`
- API conventions: `.claude/commands/api.md`
- Project specs: `docs/v0.1/`
