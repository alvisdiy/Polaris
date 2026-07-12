# Pull Request Template

## Summary
<!-- Summarize the changes introduced by this PR. Focus on "why" this change is being made rather than a line-by-line explanation of "what" changed. -->

## Specification Compliance
- [ ] This PR implements requirements from [Insert Spec Document Name/Path].
- [ ] All field names and database types match the Data Dictionary.

## Database & Migration Impact
<!-- Answer N/A if no database changes are made -->
- [ ] Reversible Alembic migration generated.
- [ ] Verified local `upgrade` and `downgrade` cycles.
- [ ] Cascade and nullable settings match database-schema-specification.md.

## Architectural Changes
- [ ] No architectural boundaries are bypassed.
- [ ] No new dependencies added without approval (check docs/v0.1/tech-stack.md).
- [ ] AI logic does not make matching/scoring decisions.

## Test Plan
<!-- Provide instructions on how to test and verify these changes. Describe manual validation and list the automated tests written. -->
- [ ] Run pytest: `pytest tests/path/to/test.py`
- [ ] Manual validation script executed: `python scripts/...`

## Checklist
- [ ] Code is formatted with Black.
- [ ] Imports are sorted with isort.
- [ ] Ruff check passes.
- [ ] Type hints verified by mypy.
- [ ] Commit history is clean and follows Conventional Commits.
