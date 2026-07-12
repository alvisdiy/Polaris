# How to Safely Refactor Code

**Scope:** Step-by-step procedure for refactoring code in Polaris without breaking behavior.

---

## When to Refactor

Refactor only when:

- The current implementation makes the codebase harder to maintain
- A spec change has made the current design incorrect
- Duplication is causing inconsistency
- The module boundary is incorrect per the architecture spec

Do NOT refactor:
- Because code style differs from your preference
- To add features "while you're in there"
- Speculatively for future requirements
- Without understanding the current behavior first

---

## Procedure

### Step 1 — Understand Current Behavior

Before touching any code:

1. Read the relevant spec document.
2. Read all code in the scope of the refactor.
3. Run the existing tests to confirm they pass.
4. Note exactly what the current code does, including edge cases.

### Step 2 — Identify the Change

Define the refactor precisely:

- What pattern is being changed?
- What modules are affected?
- What behavior must be preserved exactly?
- What behavior, if any, is being changed intentionally?

### Step 3 — Write Tests First

If tests do not exist for the behavior being changed, write them first:

```python
# Capture current behavior before refactor
def test_matching_returns_top_10_by_default():
    """Verify ranking returns Top 10 per spec before refactoring the method."""
    results = rank_scholarships(all_scholarships, profile)
    assert len(results) == 10
```

If tests already exist, run them: `pytest -v`. All must pass before you start.

### Step 4 — Refactor in Small Steps

One change at a time. After each change, run tests:

```
Change → Test → Pass → Next change
                Fail → Revert → Diagnose → Fix → Retry
```

Never accumulate multiple refactor steps before testing.

### Step 5 — Verify No Behavior Change

After all changes:

- All existing tests still pass
- API responses have the same shape
- Database queries produce equivalent results
- Logging output is equivalent

### Step 6 — Update References

If module or function names changed:

- [ ] Update all import statements
- [ ] Update `__init__.py` exports
- [ ] Update any documentation that references old names
- [ ] Update migration or config files if applicable

### Step 7 — Commit

One commit per logical refactor step. Never mix refactor commits with feature commits.

```
refactor: extract scholarship filtering to dedicated module

Moved filtering logic from matching_engine.py to filters.py
to improve testability and align with module responsibilities
per system-architecture-spesification.md.
```

---

## Safe Refactoring Patterns

### Extract Service

Moving business logic from route handlers to a service module:

1. Write test for the logic in the route
2. Extract logic to `service.py` function
3. Call service function from route
4. Verify tests still pass

### Rename Column

See `commands/migration.md`. Rename requires:
1. Migration with both old and new column name during transition
2. Update all model references
3. Update all queries
4. Remove old column in subsequent migration

### Extract Module

Splitting a large module into focused sub-modules:
1. Create new module
2. Move code, update imports
3. Re-export from original module temporarily (backwards compatibility)
4. Update all callers
5. Remove re-export when callers are updated

---

## Rules

- Tests must exist before refactoring
- Behavior must be preserved exactly unless the refactor is intentionally a bugfix
- No feature additions during refactors
- One logical refactor per commit
- Always reference the architectural principle motivating the refactor
- Never refactor code you don't fully understand

---

## Anti-Patterns

- Refactoring without tests
- Mixing feature work with refactoring
- Refactoring "because it feels wrong" without a clear goal
- Large refactors across many modules in one step
- Renaming things for style without understanding their usage
- "Cleaning up" specs or documentation without developer consensus

---

## References

- Architecture (module boundaries): `.claude/context/architecture.md`
- Coding standards (what good code looks like): `.claude/context/coding-standards.md`
- Testing procedure: `.claude/commands/tests.md`
- Workflow (commit discipline): `.claude/context/workflow.md`
