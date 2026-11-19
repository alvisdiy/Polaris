# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Students seeking scholarship opportunities. Their job is to discover relevant programs from trustworthy sources, understand eligibility and application facts, and decide which opportunities to pursue.

Scholarship reviewers/operators also use the review workflow to verify and curate records before publication; students are the primary product audience.

## Product Purpose

Polaris is a global scholarship discovery platform. It discovers scholarship opportunities from official sources, collects and verifies their information, and makes published opportunities searchable through a web application. Success means students can find relevant, actionable opportunities and inspect the facts and source evidence needed to evaluate them.

## Positioning

Polaris combines official-source provenance and human review before publication with deterministic, explainable matching. Recommendations are computed from verified scholarship facts and student profiles; AI does not determine facts, publish unreviewed data, or decide match scores.

## Operating Context

Students browse and search the public scholarship catalog, filter by available criteria, open scholarship details, inspect source links and requirements, and request personalized recommendations by providing a profile. The current application also provides comparison and browser-local saved opportunities.

Operators review pending records through the review API or CLI. Review decisions must use the review workflow so audit and version history remain intact.

## Capabilities and Constraints

- Current platform is a Vue 3 web application backed by FastAPI, PostgreSQL, SQLAlchemy, and Alembic.
- Current public capabilities include scholarship browsing/search, country and degree filtering, scholarship details, deterministic recommendations, comparison, and browser-local saved opportunities.
- Discovery and ingestion use registered/verified source practices, extraction validation, identity/deduplication, and a human-review publication boundary. Only approved records are publicly visible.
- Official sources are authoritative. Do not present unverified or inferred information as fact; missing facts remain explicitly unknown.
- Long-term direction is global coverage across academic degrees, including lesser-known opportunities, with future expansion to fellowships, internships, research grants, and exchange programs. These are direction, not claims of current coverage.
- There are no user accounts currently; saved opportunities are local to the browser. Review is currently handled through API/CLI rather than a student-facing review UI.
- Matching must remain deterministic and explainable. LLMs may assist with extraction or explanations, but must not create facts, determine match scores, or publish unreviewed data.
- No additional product-specific accessibility standard was established during init.

## Evidence on Hand

- Product vision and engineering constraints: `.claude/CLAUDE.md` and `docs/v0.1/PRD-v0.1.md`.
- Current repository status and known constraints: `docs/project-status.md` and `README.md`.
- Current database contains scholarship, provider, source, review, and discovery records; current counts are environment-specific and must be measured rather than treated as durable product claims.
- Public API implementation: `api/routers/scholarships.py` and `api/routers/recommendations.py`.
- Review and publication boundary: `services/review/` and `services/scholarship/repository.py`.
- Frontend workflows: `frontend/src/views/` and `frontend/src/api/`.
- No testimonials, customer endorsements, or independently validated outcome benchmarks were established; do not invent them.

## Product Principles

1. Official sources and traceable evidence are the source of truth.
2. Human review is required before extracted data is published.
3. Matching is deterministic, consistent, and explainable.
4. Missing or uncertain facts are represented honestly, not fabricated.
5. Prefer improving catalog relevance, completeness, and freshness before scaling discovery volume.
