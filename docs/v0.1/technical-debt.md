# Technical Debt

## TD-001
Repository currently owns transaction boundaries.

Reason:
MVP simplicity.

Future:
Move commit() to application service / Unit of Work when batch ingestion begins.

Target:
Milestone 3.x

Status:
Deferred

---

## TD-002

ScholarshipMapper performs reference resolution.

Reason:
Avoid introducing another abstraction too early.

Future:
ReferenceResolver.

Status:
Deferred

---

## TD-003

Country resolution uses exact string matching.

Future:
Normalization + ISO lookup.

Status:
Deferred

---

## TD-004

Batch persistence not implemented.

Future:
save_batch() using session.add_all() + single commit.

Status:
Deferred

---

## TD-005

N+1 lazy loading on scholarship relationships.

Location:
database/models/provider.py, country.py, university.py, source_registry.py

Context:
All new `scholarships` relationships use default `lazy="select"`.
Accessing `provider.scholarships` triggers an additional SELECT per provider.
Acceptable for single-document MVP flows.

Future:
Switch to `lazy="selectin"` or `lazy="joined"` on high-traffic relationships
when batch/list endpoints are introduced.

Trigger:
When API endpoints return collections of providers/countries with scholarship counts.

Status:
Deferred

---

## TD-006

Dual commits in persistence flow.

Location:
services/ingestion/orchestrator.py → persist_scholarship()

Context:
RawDocumentRepository.save() commits, then ScholarshipRepository.save() commits.
If the scholarship save fails, the RawDocument is already committed (orphaned).
Same pattern exists in Milestone 2.8.

Future:
Wrap entire flow in a single transaction when batch processing is introduced.
Requires removing commit() from repository save() methods.

Trigger:
Milestone 3.x batch ingestion.

Status:
Deferred

---

## TD-007

find_duplicate() defined but not called in production persistence flow.

Location:
services/scholarship/repository.py

Context:
Duplicate detection is implemented and verified, but persist_scholarship() does
not check for duplicates before saving. Running the pipeline twice on the same
document creates duplicate scholarships.

Future:
Integrate duplicate check into the persistence flow before real data ingestion.

Trigger:
Before first real (non-mock) data ingestion run.

Status:
Deferred

---

## TD-008

application_cycle always NULL.

Location:
services/scholarship/mapper.py:68

Context:
ExtractedScholarship schema has no application_cycle field. The mapper correctly
sets it to None per ADR-015 ("Never inferred; only from extracted data").
However, find_duplicate() uses application_cycle as part of the duplicate key.
Two scholarships with NULL cycle will be treated as duplicates even if they are
different cycles.

Future:
Either add application_cycle to the extraction schema, or adjust duplicate key
to handle NULL cycles gracefully.

Trigger:
When real LLM extraction begins and application_cycle data becomes available.

Status:
Deferred

---

## TD-009

Composite index missing for find_duplicate query.

Location:
services/scholarship/repository.py:45-53

Context:
find_duplicate filters on (scholarship_name, provider_id, source_id,
application_cycle). Current indexes are:
- ix_scholarship_name (scholarship_name)
- ix_scholarship_provider_cycle (provider_id, application_cycle)
PostgreSQL can use these individually but not as a single composite index.

Future:
Add composite index on (scholarship_name, provider_id, source_id,
application_cycle) when table exceeds ~100k rows.

Trigger:
Measurable query latency on find_duplicate.

Status:
Deferred