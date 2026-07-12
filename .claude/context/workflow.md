# Engineering Workflow

**Scope:** Day-to-day engineering process for working on Polaris.
**Single responsibility:** Define the workflow from task acceptance to completion.

---

## Starting Work

1. **Read the relevant spec.** Every feature maps to a document in `docs/v0.1/`.
2. **Check current state.** `git log`, `git status`, existing code in the affected modules.
3. **Identify affected modules.** Map the feature to the architecture:
   - API endpoint? → `backend/api/`
   - New model? → `database/models/`
   - Matching logic? → `matching/`
   - AI explanation? → `ai/`
   - Data ingestion? → `knowledge-pipeline/`
   - New source? → `connectors/`

---

## Planning

For any non-trivial change:

1. **Write down** what the spec says the feature should do.
2. **List** the files that need to be created or modified.
3. **Identify** any spec gaps or ambiguities — resolve before coding.
4. **Decide** if new dependencies or architectural patterns are needed.

---

## Implementation

1. **Models first.** If the feature touches data, define models/schemas before logic.
2. **Services second.** Implement business logic with clear inputs and outputs.
3. **Routes third.** Wire up API endpoints with thin handlers.
4. **Tests.** Write tests alongside or immediately after implementation.
5. **Minimum viable.** Ship the simplest version that satisfies the spec.

### Code Style

Follow `context/coding-standards.md` for all code written.

### Key References

- Model conventions: `context/database.md`
- API patterns: See commands
- Connector pattern: See commands

---

## Review

### Self-Review

Before considering work done, check:

- [ ] All code follows SQLAlchemy 2 style (`database/models/base.py`)
- [ ] New models use `TimestampMixin`
- [ ] No hardcoded URLs, secrets, or magic numbers
- [ ] No LLM calls for matching/scoring
- [ ] Pydantic validation on all external input
- [ ] Follows coding standards in `context/coding-standards.md`

### Peer Review

When reviewing others' code:

1. Read the spec the change targets.
2. Check correctness against the spec.
3. Verify no anti-patterns from this kit.
4. Check for unnecessary complexity.
5. Approve with clear, actionable feedback.

---

## Finishing Work

1. **Verify** the change works end-to-end.
2. **Run** linting and type checking.
3. **Write** a clear commit message referencing the feature/spec.
4. **Update** any documentation if the implementation diverged from the spec.
5. **Do NOT commit** secrets, `.env`, or `__pycache__`.

---

## Commit Messages

Format:

```
<type>: <short description>

<optional body — why, not what>
```

Types:

- `feat` — New feature
- `fix` — Bug fix
- `refactor` — Code restructuring without behavior change
- `docs` — Documentation only
- `chore` — Tooling, config, dependencies
- `test` — Adding or updating tests

Example:

```
feat: add scholarship model with provider relationship

Implements the core Scholarship table as defined in
database-schema-specification.md.
```

---

## Branch Strategy

- `main` — Stable, production-ready
- `develop` — Active development
- Feature branches from `develop`

---

## Daily Flow

```
Morning
  → Pull latest develop
  → Check for spec updates
  → Pick up task

During Work
  → Read spec → Plan → Implement → Test → Review

End of Day
  → Commit work in progress (if substantial)
  → Push to feature branch
  → Note any blockers
```

---

## Anti-Patterns

- Implementing without reading the spec first
- Skipping self-review
- Mixing unrelated changes in one commit
- Committing directly to `main` or `develop`
- Large PRs that span multiple concerns
- "I'll fix it in the next PR"
