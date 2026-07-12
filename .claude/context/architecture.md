# Architecture Reference

**Scope:** Summarizes architecture decisions for quick reference during implementation.
**Does NOT replace:** `docs/v0.1/system-architecture-spesification.md` and `docs/v0.1/architecture-decision-record.md`.

---

## System Overview

Polaris is a **Modular Monolith** with clean module boundaries. Architecture supports future decomposition into microservices.

```
User → Frontend → Backend API → Matching Engine + AI Engine → Scholarship Database
```

---

## Core Modules

| Module | Responsibility | Spec Reference |
|--------|---------------|----------------|
| Frontend | Search, profile form, results display | `system-architecture-spesification.md` §2 |
| Backend API | Request validation, orchestration | `system-architecture-spesification.md` §3 |
| Matching Engine | Filtering, weighted scoring, ranking | `matching-engine-design-specification.md` |
| AI Engine | LLM explanations from matching results | `matching-engine-design-specification.md` §8 |
| Knowledge Pipeline | Crawl, clean, extract, validate, store | `knowledge-pipeline.md` |
| Source Registry | Official source metadata catalog | `source-registry-specification.md` |
| Connectors | Per-source content adapters | `connector-specification.md` |

---

## Request Flow

```
User Profile
    → Input Validation (Pydantic)
    → Profile Normalization
    → Scholarship Filtering (deterministic)
    → Weighted Scoring (deterministic)
    → Ranking (deterministic)
    → Gap Analysis (deterministic)
    → LLM Explanation (AI — explanation only)
    → Recommendation Response
```

---

## Data Flow

```
Official Website → Connector → Cleaner → AI Extractor → Validator → Human Review → Knowledge Base
```

---

## Key ADRs (Quick Reference)

| ADR | Decision | Rationale |
|-----|----------|-----------|
| ADR-001 | Modular Monolith | Simpler than microservices, MVP-appropriate |
| ADR-002 | FastAPI | Async, performance, OpenAPI auto-gen |
| ADR-003 | PostgreSQL | Relational, JSONB, production-proven |
| ADR-004 | SQLAlchemy 2 | Mature, flexible, widely used |
| ADR-005 | Playwright | JS rendering, stable, modern |
| ADR-007 | Connector Pattern | Per-source adapters, no if-else chains |
| ADR-008 | Source Registry | Centralized crawl configuration |
| ADR-009 | Knowledge Base | Pre-crawled data, not real-time |
| ADR-010 | LLM not Source of Truth | AI explains, never creates facts |
| ADR-011 | Deterministic Matching | Consistent, explainable, testable |
| ADR-012 | Human Review | All AI data verified before publish |
| ADR-013 | Opportunity-first | Extensible to fellowship, internship, etc. |

---

## Module Dependencies

```
connectors/       → depends on source_registry
knowledge_pipeline/ → depends on connectors/, validator, extractor
matching_engine/  → depends on scholarship database
ai_engine/        → depends on matching_engine output only
backend_api/      → depends on matching_engine/, ai_engine/
```

---

## Anti-Patterns

- LLM calling database directly for matching
- Hardcoded URLs outside Source Registry
- Real-time crawling for search queries
- AI generating facts not in Knowledge Base
- One connector handling multiple source types
- Business logic in API route handlers

---

## Future Considerations

- Module extraction to microservices when team/codebase grows
- Event-driven communication between modules
- Caching layer for frequent queries
- Rate limiting per connector
- Monitoring and observability stack
