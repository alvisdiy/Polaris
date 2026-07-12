# Commit Convention

**Purpose:** This document establishes the Conventional Commits standard for all commits in the Polaris repository. Consistent commit messages ensure readable history, automate changelogs, and simplify reviews.

---

## Specification

All commit messages must follow this structure:

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

---

## Commit Types

| Type | Description |
|---|---|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation changes only |
| `refactor` | A code change that neither fixes a bug nor adds a feature |
| `test` | Adding missing tests or correcting existing tests |
| `perf` | A code change that improves performance |
| `chore` | Changes to the build process, auxiliary tools, or libraries |
| `ci` | Changes to CI configuration files and scripts |
| `style` | Changes that do not affect the meaning of the code (formatting, linting) |

---

## Scope Guidelines

Optional but recommended. Scopes correspond to codebase modules:

- `db` — Database schemas, models, migrations
- `api` — FastAPI routers, schemas, dependencies
- `pipeline` — Ingestion logic, cleaning, crawling
- `matching` — Matching engine, scoring logic, ranking
- `connector` — Provider connectors (e.g., `connector(mext)`)
- `ai` — LLM extraction prompts, insight generations
- `config` — Env variables, config files

---

## Naming Rules

1. **Imperative Mood:** Use the imperative mood in the description ("add feature", not "added feature" or "adds feature").
2. **No Period:** Do not end the description with a period.
3. **Lowercase:** Start the description with a lowercase letter.
4. **Length limit:** Keep the first line under 72 characters.
5. **Breaking Changes:** Indicated by a `!` after the type/scope, and a `BREAKING CHANGE:` footer.

---

## Commit Message Checklist

- [ ] Commit type is lowercase and matches the allowed list.
- [ ] Description is in the imperative mood and does not end with a period.
- [ ] Breaking changes use the `!` indicator and have details in the footer.
- [ ] Commit contains exactly one logical change (no "add country model and fix login bug").

---

## Examples

### Correct Commit Messages

#### New Feature
```
feat(db): add provider and country models with UUID keys

Implements the initial reference models defined in
database-schema-specification.md.
```

#### Bug Fix
```
fix(pipeline): prevent crawler timeout on slow official page

Adds an exponential backoff retry mechanism (max 3 retries)
when fetching MEXT application lists.
```

#### Refactoring
```
refactor(matching): optimize ranking loop performance

Replaces python list sorting with an index-based filter
to reduce execution time under heavy loads.
```

#### Documentation
```
docs(readme): add docker deployment instructions
```

#### Breaking Change
```
feat(db)!: drop legacy string key columns from country table

BREAKING CHANGE: Country keys are now UUIDs. Old string keys
are no longer supported in provider foreign key lookups.
```

---

## Anti-Patterns
- Committing with vague descriptions (e.g., `fix bug`, `updates`, `work in progress`).
- Mixing multiple concerns in one commit (e.g., `feat: implement uni model and fix pipeline config`).
- Capitalizing the description (e.g., `feat(api): Add search route`).
- Using past tense (e.g., `docs: updated contribution guide`).
- Ending description with punctuation (e.g., `fix(api): fix credentials validation.`).

---

## References
- Workflow guide: `.claude/context/workflow.md`
- Branching strategy: `docs/engineering/branching-strategy.md`
- Conventional Commits: `https://www.conventionalcommits.org/`
