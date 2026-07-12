# Code Review Checklist

**Purpose:** This document provides reviewers with a structured list of checks to perform on every pull request. It ensures code quality, architectural integrity, performance, and security standard compliance.

---

## Technical Priorities

1. **Correctness & Spec Compliance** — Does the code satisfy the specification?
2. **Security** — Are there vulnerabilities or exposed secrets?
3. **Architecture & Boundaries** — Does the change respect module boundaries?
4. **Maintainability & Readability** — Is the code simple and clean?

---

## Review Checklist

### 1. Product & Architecture Specs
- [ ] **No logic deviation:** Verify field names, types, and logic match the specifications in `docs/v0.1/`.
- [ ] **No AI decision-making:** Ensure Large Language Models are only used for extraction, translation, or explanation. The matching engine and scoring logic must remain deterministic.
- [ ] **No speculative code:** Reject abstractions built for "future requirements" that are not in the current spec.

### 2. Database & Migrations
- [ ] **Model design:** Verify tables use UUID primary keys and follow the mapped_column SQLAlchemy 2.0 style.
- [ ] **Cascade rules:** Ensure delete cascades follow database-schema-specification.md (e.g., deleting a provider must not drop scholarships).
- [ ] **Migration check:** Verify the migration file is clean, only contains changes related to the PR, and implements both `upgrade()` and `downgrade()`.
- [ ] **Index coverage:** Check if foreign key and filter columns have appropriate database indexes.

### 3. Naming, Typing, and Structure
- [ ] **Naming conventions:** Variables, modules, functions follow snake_case; classes follow PascalCase.
- [ ] **Type safety:** All public functions, model definitions, and Pydantic schemas have complete type annotations.
- [ ] **Layer separation:** FastAPI route handlers must be thin. Business logic must live in the service layer.

### 4. Code Quality & Technical Debt
- [ ] **SOLID principles:** Verify modules have a single responsibility.
- [ ] **No duplication:** Identify and reject duplicated logic or utility code.
- [ ] **No magic numbers:** Configuration and limits must be defined in constants or read from environment variables.
- [ ] **Simple code:** Favour simple, direct implementations over clever, complex abstractions.

### 5. Performance & Resource Limits
- [ ] **No N+1 queries:** Ensure relationship loading uses `joinedload` or `selectinload` where appropriate.
- [ ] **Rate limits:** Connectors must apply rate limits and retry mechanism backoffs (max 3 retries).
- [ ] **Garbage collection:** Ensure resources (like Playwright browser contexts or DB connections) are closed properly in `finally` blocks.

### 6. Security & Data Validation
- [ ] **No secrets:** Ensure no API keys, credentials, or private configuration values are committed.
- [ ] **Input validation:** Ensure all data entering the system is validated using Pydantic schemas.
- [ ] **Pending Review:** Extraction results must default to `pending_review` verification status.

---

## Examples

### Good Review Feedback
- "Line 24: This query will execute an N+1 query since `scholarship.provider` is loaded lazily. Use `selectinload(Scholarship.provider)` to fetch them in one query."
- "Line 42: The table column type is declared as String(3) for country code, but the database schema spec section 3.2 defines country_id as a UUID. Please refactor to UUID and map the country code to an `iso3` column."

---

## Anti-Patterns
- Reviewing style issues (like whitespace or import sorting) manually when they should be resolved automatically by linters.
- Approving PRs without checking if the corresponding database migration can be rolled back.
- Allowing logic that queries database tables directly from FastAPI endpoints without going through a service layer.

---

## References
- Code review playbook: `.claude/commands/review.md`
- Database standards: `.claude/context/database.md`
- System architecture: `.claude/context/architecture.md`
