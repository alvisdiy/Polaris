# How to Review Code

**Scope:** Step-by-step procedure for reviewing code in Polaris.

---

## Purpose

Code review ensures every change:

- Aligns with project specifications
- Follows coding standards
- Does not introduce architectural violations
- Does not introduce security vulnerabilities

---

## Procedure

### Step 1 — Understand Context

1. Read the PR description or commit message.
2. Identify which spec document the change targets.
3. Open that spec and keep it as reference.

### Step 2 — Check Spec Compliance

For every new model, field, or behavior:

- [ ] Field names match `docs/v0.1/data-dictionary.md`
- [ ] Types match the Data Dictionary
- [ ] Relationships match `docs/v0.1/database-schema-specification.md`
- [ ] Business logic matches the relevant feature spec
- [ ] Matching logic is deterministic (no LLM involvement)
- [ ] AI is used only for explanation, not scoring

### Step 3 — Check Coding Standards

- [ ] Follows naming conventions in `context/coding-standards.md`
- [ ] Type hints on all function signatures
- [ ] Import order: stdlib → third-party → local
- [ ] No `import *`
- [ ] No circular imports
- [ ] No global mutable state

### Step 4 — Check Architecture

- [ ] Business logic is in service layer, not in routes
- [ ] No new dependencies added without justification
- [ ] No hardcoded URLs, secrets, or magic numbers
- [ ] Module boundaries respected (no cross-module direct DB access)
- [ ] New models use `TimestampMixin`
- [ ] Pydantic validation on external input

### Step 5 — Check Data Safety

- [ ] AI-extracted data has `pending_review` status
- [ ] No data published without human review step
- [ ] Database changes have proper migration with `downgrade()`
- [ ] No cascading deletes that violate schema spec constraints
- [ ] URLs come from Source Registry, not hardcoded

### Step 6 — Check Security

- [ ] No secrets in code or comments
- [ ] No SQL injection vectors (use ORM, not raw SQL)
- [ ] Input validation on all user-facing endpoints
- [ ] No path traversal in file operations

### Step 7 — Provide Feedback

- Be specific: reference line numbers and spec sections.
- Categorize issues: **Must fix** (blocks merge) vs **Suggestion** (nice to have).
- Explain why, not just what.

---

## Rules

- Every review checks spec compliance first, style second.
- Do not approve changes that violate ADR decisions.
- Do not approve new dependencies without checking `docs/v0.1/tech-stack.md`.
- Prefer actionable feedback over vague criticism.

---

## Anti-Patterns

- Approving without reading the relevant spec
- Nitpicking style when there are correctness issues
- Blocking on personal preferences not in coding standards
- "LGTM" without actually reviewing
- Reviewing only the diff without understanding the feature context

---

## References

- Coding standards: `.claude/context/coding-standards.md`
- Database conventions: `.claude/context/database.md`
- Architecture: `.claude/context/architecture.md`
- AI rules: `.claude/context/ai-rules.md`
