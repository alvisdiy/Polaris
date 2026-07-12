# ADR-015

## Decision

Scholarship is the central aggregate root of the domain model.

### Reference Entities (read-only lookup)

- Provider
- Country
- University
- SourceRegistry

### Child Entities (owned by Scholarship, cascade-delete)

- Requirement
- Benefit
- Timeline
- Version (audit history, never deleted)

### Duplicate Detection

Belongs to the service layer.

Database constraints are only for relational integrity (FK, NOT NULL).

No UNIQUE constraint is used for deduplication.

### Application Lifecycle

Represented by `extraction_status` on the Scholarship table.

```text
pending_review → approved | rejected | superseded → archived
```

### Application Cycle

`application_cycle` is NEVER inferred or derived by the mapper.

It is only mapped from extracted data.

If unavailable, persist NULL.

### field_of_study

Stored as PostgreSQL `ARRAY(TEXT)`.

Chosen over JSONB because the value is guaranteed to remain a simple
array of strings throughout the MVP. If future requirements demand
nested structures or partial-match queries on array elements, migrate
to JSONB at that point.

---

## Rationale

- Scholarship is the core business object. All other tables serve it.
- Reference entities avoid duplicated name columns on Scholarship.
- Child entities keep the Scholarship table focused on core attributes.
- Service-layer deduplication allows flexible business rules (e.g.,
  same name + same cycle + same source = duplicate) without rigid
  DB constraints.
- `extraction_status` models the human-review pipeline without
  conflating it with data validity.

---

## Trade-offs

- `ARRAY(TEXT)` cannot store metadata per entry (e.g., whether a
  field of study is "primary" or "accepted"). JSONB would support
  this. Accepted for MVP; revisit if per-entry metadata is needed.
- No DB-level deduplication means concurrent inserts could produce
  duplicates under race conditions. Service-layer locking or
  idempotency tokens should be added when concurrency is a concern.
