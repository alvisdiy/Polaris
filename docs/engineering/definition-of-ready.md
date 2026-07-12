# Definition of Ready (DoR)

**Purpose:** This document defines the checklist of requirements that a feature, bug fix, or task must meet before an engineer can begin active implementation. It prevents starting work on incomplete or ambiguous specifications.

---

## Responsibilities

- **Product Owner (PO):** Ensures product requirements, user flows, and acceptance criteria are documented.
- **Architect/Tech Lead:** Ensures technical architecture impact, database schema, and design patterns are defined.
- **Developer:** Reviews the specifications to ensure clarity, identifies technical blockers, and raises questions before beginning implementation.

---

## Process

1. **Backlog refinement:** The PO and Tech Lead review the task.
2. **Documentation Check:** Check if the relevant specification exists in `docs/v0.1/` or has been updated.
3. **Dependency Check:** Identify any database schema changes or library dependencies.
4. **Risk Assessment:** Assess performance, security, and scalability impacts.
5. **Approval:** The task is moved to "Ready" status once the checklist is satisfied.

---

## Checklist

- [ ] **Specification Complete:** The feature is described in an approved product document (e.g., `docs/v0.1/PRD-v0.1.md` or a feature spec).
- [ ] **Acceptance Criteria Defined:** Clear criteria exist for how the feature is verified (e.g., input values, expected outputs, error cases).
- [ ] **Architecture Understood:** The technical design fits into the Polaris architecture (e.g., Modular Monolith) without violating existing ADRs.
- [ ] **Database Schema Defined:** If database changes are needed, the new schema, columns, constraints, and relationships are designed (in code or documentation).
- [ ] **Dependencies Resolved:** All third-party libraries needed are approved and listed in the tech stack.
- [ ] **Risks Identified:** Data privacy, extraction accuracy, API performance, and rate-limiting rules are identified.
- [ ] **Estimation / Scope Defined:** The boundary of the task is clear (e.g., "This milestone only implements the API routing layer; database logic is mocked").

---

## Examples

### Task Ready to Start
- **Title:** "Implement MEXT Crawler using Playwright"
- **Context:** The entry URL is registered in the Source Registry, target elements are documented, `robots.txt` compliance is evaluated, Playwright is installed, and the Connector contract is defined in `docs/v0.1/connector-specification.md`.
- **Status:** **Ready**

---

## Anti-Patterns
- Starting coding based on a Slack message or verbal agreement without updating the relevant project specifications.
- Commencing work on an API route before the database schema it relies on is defined.
- Writing a crawler for a source before confirming whether the source requires login credentials or is blocked by robots.txt.

---

## References
- Project Specs: `docs/v0.1/`
- Architecture Spec: `docs/v0.1/system-architecture-spesification.md`
- Engineering workflow: `.claude/context/workflow.md`

---

## Future Considerations
- Integrate DoR checks directly into issue tracking templates (e.g., GitHub Issues or Linear).
