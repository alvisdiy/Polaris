# AI Assistant Rules

**Scope:** How AI coding assistants (Claude Code, Codex, Cursor, etc.) should behave when working on Polaris.
**Single responsibility:** Define AI-specific constraints and expectations.

---

## Core Principle

AI is a tool, not a decision-maker. It follows specs, not intuition.

---

## When AI Is Allowed

- Implementing features described in spec documents
- Writing tests for implemented logic
- Refactoring code while preserving behavior
- Generating boilerplate that follows established patterns
- Explaining existing code or architecture
- Reviewing code against coding standards
- Creating database migrations from model changes
- Writing documentation for new modules

---

## When AI Must Ask First

- Adding a new dependency not in `docs/v0.1/tech-stack.md`
- Modifying database schema in ways not covered by existing specs
- Changing architectural patterns or module boundaries
- Modifying the Knowledge Pipeline flow
- Changing matching weights or scoring algorithms
- Any change that affects published API contracts
- Working outside the current MVP scope

---

## When AI Is Forbidden

- Committing directly to `main` without review
- Deciding product requirements or feature scope
- Adding features not in any spec document
- Bypassing human review for data publication
- Using LLM for scholarship matching or scoring
- Hardcoding secrets, API keys, or credentials
- Modifying spec documents without explicit request

---

## How AI Should Use Documentation

### Priority Order

1. **CLAUDE.md** — Start here. Understand project identity and rules.
2. **Spec documents** (`docs/v0.1/`) — Read the relevant spec BEFORE implementing.
3. **Context documents** (`.claude/context/`) — Understand standards and patterns.
4. **Command documents** (`.claude/commands/`) — Follow step-by-step procedures.
5. **Existing code** — Reference established patterns.

### Rules

- Read the spec BEFORE writing any code.
- Do not guess field names, types, or relationships — the specs define them.
- If the spec is ambiguous, flag it rather than guessing.
- Never duplicate information from specs into generated code comments.
- Reference spec sections when explaining implementation decisions.

---

## How AI Should Handle Data

| AI Can | AI Cannot |
|--------|-----------|
| Extract text from crawled content | Create scholarship data from memory |
| Validate data against Pydantic schemas | Publish data without `pending_review` status |
| Normalize field values per Data Dictionary | Decide whether a scholarship exists |
| Flag missing required fields | Auto-approve extracted data |
| Generate explanations from matching results | Generate matching scores |

---

## How AI Should Write Code

1. **Follow existing patterns.** Check `database/models/base.py`, `database/session.py`, existing code before inventing new patterns.
2. **Minimal changes.** One concern per commit. No drive-by refactors.
3. **No speculative features.** Implement what the spec requires, not what might be needed later.
4. **No new dependencies** without explicit approval.
5. **No magic.** All behavior should be traceable to a spec or documented decision.

---

## AI Review Checklist

When AI completes a task, verify:

- [ ] All changes trace to a spec requirement
- [ ] No new dependencies added
- [ ] No hardcoded values
- [ ] Follows SQLAlchemy 2 conventions
- [ ] Pydantic validation on all inputs
- [ ] No LLM calls for matching/scoring
- [ ] No architectural changes beyond scope
- [ ] Code follows `context/coding-standards.md`

---

## Handling Spec Gaps

If a spec doesn't cover a specific implementation detail:

1. **Stop.** Do not guess.
2. **Document** the gap.
3. **Suggest** a resolution that aligns with the spec's design principles.
4. **Wait** for confirmation before implementing.

---

## Anti-Patterns

- "I know better than the spec" — you don't
- Adding error handling the spec didn't request
- Creating abstractions for hypothetical future needs
- Rewriting existing code for style reasons
- Suggesting architectural changes mid-implementation
- Treating AI-generated code as automatically correct
