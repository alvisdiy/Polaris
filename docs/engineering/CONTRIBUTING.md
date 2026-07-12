# Contributing to Polaris

**Purpose:** This document guides new and existing developers on how to set up, build, test, and contribute code to Polaris. It establishes the baseline quality expectations and operational steps for development.

---

## Developer Onboarding & Environment Setup

### 1. Prerequisites
- Python 3.13 (or >= 3.11 as defined in `pyproject.toml`)
- PostgreSQL database
- Git
- Playwright (if working on crawlers)

### 2. Repository Setup
```bash
# Clone the repository
git clone git@github.com:Gitlawb/openclaude.git polaris
cd polaris

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .
```

### 3. Environment Variables
Copy `.env.example` to `.env` and fill in the values:
```bash
cp .env.example .env
```
Ensure your `DATABASE_URL` is configured correctly:
`postgresql+psycopg://postgres:password@localhost:5432/polaris`

### 4. Database Setup & Migration
Apply migrations to bring your local database schema up to date:
```bash
alembic upgrade head
```

---

## Coding Standards

All contributions must adhere to the standards in `.claude/context/coding-standards.md`.
- **Formatting:** Code must be formatted using Black.
- **Linting:** Code must pass Ruff check.
- **Imports:** Imports must be sorted using isort.
- **Static Typing:** Type annotations are required on all functions and checked with mypy.

Run check suite locally:
```bash
ruff check .
black --check .
isort --check-only .
mypy .
```

---

## Testing Workflow

- **Framework:** pytest (see `.claude/commands/tests.md`).
- **Isolation:** Tests must not connect to external HTTP APIs. Mock these interfaces.
- **Database:** Integration tests must run against a clean database instance. Use transaction rollback between tests.
- **Running tests:**
```bash
pytest
```

---

## Development & Commit Workflow

1. **Check the Definition of Ready:** Do not start coding until the task is Ready (see `definition-of-ready.md`).
2. **Create a Branch:** Follow the naming rules in `branching-strategy.md`.
3. **Write Code & Migrations:** Implement changes in small, logical steps. Create migrations per `migration.md` if the database changes.
4. **Follow Commit Convention:** Make commits following `commit-convention.md`.
5. **Verify Against Definition of Done:** Confirm all criteria in `definition-of-done.md` are met.
6. **Submit a Pull Request:** Create a PR using the template in `pull-request-template.md`.

---

## Peer Review Expectations

- All code must be reviewed by at least one maintainer.
- Reviews must follow the checklist in `code-review-checklist.md`.
- Be constructive: comment on correctness, scalability, and adherence to specs first, formatting/style second.

---

## Checklist

- [ ] Python virtual environment created and active
- [ ] Local Postgres DB running and alembic migrations applied
- [ ] Code passes all pre-commit hooks (Ruff, Black, isort)
- [ ] Types are verified by mypy
- [ ] Tests run successfully with no failures
- [ ] Commit messages follow the Conventional Commits specification

---

## Examples

### Good Contribution Setup
1. Reads PRD and database specification for matching engines.
2. Implements `matching_engine.py` with type annotations.
3. Formats with `black` and runs `pytest`.
4. Commits with `feat: add weighted matching score calculations`.

---

## Anti-Patterns
- Committing without running tests or static linters locally.
- Modifying schema files manually inside Postgres instead of using Alembic migrations.
- Adding dependencies to `pyproject.toml` without team approval.
- Storing secrets or local config values in code or commits.

---

## References
- Coding standards: `.claude/context/coding-standards.md`
- Branching strategy: `docs/engineering/branching-strategy.md`
- Commit convention: `docs/engineering/commit-convention.md`
- Database standards: `.claude/context/database.md`

---

## Future Considerations
- Automate pre-commit checks using git hooks.
- Configure GitHub Actions to run linters, type checkers, and tests on every push.
