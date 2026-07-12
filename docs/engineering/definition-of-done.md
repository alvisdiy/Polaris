# Definition of Done (DoD)

**Purpose:** This document defines the quality gates that a feature, bug fix, or task must pass before it is considered complete and ready to be merged into the `develop` branch. It ensures consistency, correctness, and operational safety.

---

## Responsibilities

- **Developer:** Completes coding, self-review, tests, migrations, and documentation before submitting.
- **Reviewer:** Verifies code correctness, architectural compliance, and testing standards.
- **CI System / Automation:** Runs static checks, linters, and test suites automatically.

---

## Process

1. **Development complete:** All code changes are written.
2. **Self-Review:** The developer runs through the DoD checklist.
3. **Local Testing:** Linters, formatting, and unit tests run and pass locally.
4. **Peer Review:** Code undergoes code review and receives approval from at least one engineer.
5. **Architecture verification:** Verify that no new architectural violations are introduced.

---

## Checklist

- [ ] **Implementation Complete:** The code satisfies all acceptance criteria defined in the feature spec.
- [ ] **Coding Standards Followed:** Code is formatted with Black, import sorted by isort, passes Ruff, and has type annotations checked by mypy.
- [ ] **Tests Written & Passed:** Unit tests cover success, failure, and boundary conditions. No tests mock internal implementation details.
- [ ] **Database Migration Generated & Verified:** If DB models changed, a dedicated, reversible Alembic migration exists. `upgrade()` and `downgrade()` have been tested successfully.
- [ ] **No Hardcoded Secrets or Configs:** All configuration is read from env variables or database settings. No credentials are committed.
- [ ] **AI-Rules Followed:** AI did not make matching/scoring decisions. Extraction output starts with `pending_review` status.
- [ ] **Documentation Synchronized:** The relevant documentation files in `docs/v0.1/` or `README.md` are updated if the implementation diverged from the original specification.
- [ ] **PR Template Filled:** The PR description clearly documents the motivation, migration steps, and test instructions.

---

## Examples

### Definition of Done Met
1. `provider` table columns added.
2. Alembic migration `create_provider_table.py` generated.
3. local `alembic upgrade head && alembic downgrade -1` run and passed.
4. Unit tests in `tests/test_models/test_provider.py` written and passing.
5. Code formatted with Black.
6. Pull Request created using the PR template.
7. PR reviewed and approved.

---

## Anti-Patterns
- Marking a task "Done" because code is complete, but testing or migrations are deferred to a "follow-up task."
- Committing migrations without testing their `downgrade()` script.
- Merging PRs with failing lint checks or partial test failures.
- Merging model modifications without checking if relationships or cascade deletes violate the schema specification.

---

## References
- Database migration playbook: `.claude/commands/migration.md`
- Testing playbook: `.claude/commands/tests.md`
- Review playbook: `.claude/commands/review.md`

---

## Future Considerations
- Enforce the DoD checklist via automated status checks in GitHub pull requests.
