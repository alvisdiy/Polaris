# Polaris — Global Scholarship Intelligence Platform

Polaris is a global scholarship intelligence platform that discovers,
collects, verifies, structures, and maintains scholarship opportunities
from official sources around the world.

Its primary goal is to make the world's scholarship opportunities
discoverable and understandable in one place.

Polaris then uses structured scholarship data to help students:
- discover opportunities,
- search and filter scholarships,
- understand eligibility and requirements,
- identify suitable opportunities,
- compare scholarships,
- prepare applications,
- and reach official application pages.

## Project Objective

Tujuan utama project saat ini bukan lagi mendesain arsitektur.

Architecture, data model, matching design, source registry, connector pattern, dan knowledge pipeline sudah dirancang.

Sekarang fokus utama adalah:

> **Mengubah desain Polaris menjadi sistem yang benar-benar berjalan menggunakan data beasiswa nyata.**

Jangan melakukan redesign architecture tanpa alasan kuat dari implementasi nyata.

---

# Product Vision

Polaris adalah Scholarship Intelligence Platform yang membantu mahasiswa dalam seluruh perjalanan beasiswa:

```text
Understand Profile → Discover → Match → Understand Fit → Identify Gaps → Compare → Prepare → Apply
```

Tujuan akhir: platform bantuan beasiswa yang komprehensif, bukan sekadar demo.

Produk akan berkembang menjadi:

* Profile Intelligence — memahami kekuatan & kelemahan mahasiswa.
* Personalized Matching — rekomendasi berdasarkan profil unik.
* Requirement Analysis — analisis kelayakan eligibility secara detail.
* Comparison — perbandingan antar beasiswa secara side-by-side.
* Preparation Guidance — panduan persiapan aplikasi.
* Application Tracking — pelacakan status aplikasi.

---

# AI Engineering Direction

AI is used to solve real problems in the scholarship data lifecycle.

Potential areas:
- information extraction
- document understanding
- scholarship classification
- entity normalization
- duplicate detection
- requirement extraction
- semantic search
- recommendation
- ranking
- user feedback learning

AI must not invent scholarship facts.
Official sources and validated Knowledge Base remain authoritative.

Polaris juga menjadi AI Engineering project. Kita akan membangun dan melatih model ML/DL sendiri, termasuk:

* Data preparation & feature engineering.
* Model training & evaluation.
* Model saving, inference & API serving.
* Product integration (matching engine + AI model).

**First AI task** ditentukan oleh data/ML feasibility audit:

* Scholarship Eligibility/Fit Prediction adalah arah yang diinginkan.
* Jangan asumsikan valid sampai data & labeling strategy dievaluasi.
* Jangan fabricate dataset, labels, atau model performance.
* Dokumentasikan limitation dengan jelas.

---

# Current Architecture

Polaris menggunakan Modular Monolith.

High-level structure:

```text
polaris/

apps/
├── web/
├── api/
└── admin/

services/
├── knowledge-pipeline/
│   ├── crawler/
│   ├── cleaner/
│   ├── extractor/
│   ├── validator/
│   ├── scheduler/
│   └── connectors/
│
├── matching-engine/
└── ai-engine/

packages/
├── shared/
├── schemas/
└── utils/

database/
├── migrations/
└── seed/

docs/
```

Technology stack:

* Python 3.13
* FastAPI
* PostgreSQL
* SQLAlchemy 2
* Alembic
* Pydantic v2
* Playwright
* Crawl4AI
* Trafilatura
* Markdownify
* APScheduler
* pytest
* Ruff
* Black
* mypy
* Docker / Docker Compose

---

# Important Architecture Rules

These rules are already decided and should be respected.

## 1. Official Source First

Polaris only treats official sources as authoritative.

Examples:

* Government
* Embassy
* National scholarship agencies
* Official universities
* Official foundations
* International organizations

Blog, Reddit, social media, forums, and unofficial portals are not authoritative sources.

---

## 2. LLM Is Not Source of Truth

LLM may:

* extract structured information,
* summarize information,
* explain recommendations,
* help compare verified information.

LLM must NOT:

* invent scholarship requirements,
* invent benefits,
* change Match Score,
* determine eligibility independently,
* create facts that are not present in the Knowledge Base.

---

# Knowledge Pipeline

The intended pipeline is:

```text
Official Source
      ↓
Source Registry
      ↓
Connector
      ↓
Crawler
      ↓
Cleaner
      ↓
AI Extractor
      ↓
Schema Validator
      ↓
Human Review
      ↓
Scholarship Knowledge Base
```

The Source Registry is the gatekeeper.

A crawler must never crawl an unregistered source.

---

# Matching Engine

The Matching Engine is deterministic.

Pipeline:

```text
User Profile
      ↓
Profile Validation
      ↓
Profile Normalization
      ↓
Repository
      ↓
Filter Engine
      ↓
Scoring Engine
      ↓
Ranking Engine
      ↓
Explanation Engine
```

The current approved matching design uses:

| Criterion           |  Weight |
| ------------------- | ------: |
| Country             |      20 |
| Degree              |      20 |
| Field of Study      |      20 |
| GPA                 |      15 |
| Language            |      10 |
| Funding             |       5 |
| Research Experience |       5 |
| Work Experience     |       3 |
| Leadership          |       2 |
| **Total**           | **100** |

Important:

Country, Degree, and Field of Study are scoring criteria, NOT hard filters.

The only MVP mandatory matching filter is:

```text
application_deadline >= today
OR application_deadline IS NULL
```

`extraction_status = approved` is a repository-level data-governance gate.

---

# Current Project State

**Implemented and verified:**

* PostgreSQL + Alembic migration path working on real PostgreSQL.
* 19 real, verified, approved scholarships from official sources.
* Deterministic Matching Engine (Filter → Score → Rank → Explain).
* REST API: `POST /api/v1/matching`, `GET /api/v1/scholarships`, `GET /api/v1/scholarships/{id}`.
* Scholarship discovery list with filters (query, country, degree).
* Scholarship detail endpoint with requirements, benefits, timeline, provider, source, official URL.
* End-to-end vertical slice validated: DB → seed → repository → matching → ranking → explanation → API.
* 195 passing tests covering matching engine, scoring, ranking, explanation, API contract, and real-data edge cases.
* Initial vanilla SPA frontend with profile matching, scholarship list, detail modal, and comparison view.
* Official-source traceability preserved: every scholarship links back to source registry entry.

**Not yet implemented:**

* AI/ML model (eligibility/fit prediction) — pending data & labeling feasibility audit.
* User authentication & profile persistence.
* Application tracking / dashboard.
* Automated crawling pipeline (crawlers still manual/seed-based).
* Advanced filtering (field of study, deadline range, funding type).

---

# Development Direction

Polaris sekarang fokus pada:

1. **Product polish** — menjadikan platform benar-benar usable oleh mahasiswa:
   * Clean, modern UI/UX.
   * Navigasi jelas: Discover → Match → Understand Fit → Compare → Apply.
   * Scholarship cards dengan score, deadline urgency, funding, country, degree.
   * Visual hierarchy untuk Match Score, strengths, gaps, deadline urgency.
   * Loading, empty, error, no-match states.
   * Responsive mobile/desktop layout.
   * Clear CTAs ke official application links.
   * Profile form yang tidak overwhelming.

2. **Knowledge Base quality** — menjaga agar data tetap:
   * Official sources only.
   * Verified & accurate requirements, benefits, deadlines.
   * Source traceability.
   * Freshness (regular update mechanism).

3. **AI Engineering** — setelah produk stabil:
   * Data/ML feasibility audit untuk Scholarship Eligibility/Fit Prediction.
   * Bukan asumsi — validasi dulu data & labeling strategy.
   * Jangan fabricate dataset, labels, atau model performance.

4. **Product evolution** — platform akan berkembang menjadi:
   * Profile intelligence.
   * Personalized matching.
   * Requirement analysis.
   * Comparison.
   * Preparation guidance.
   * Application tracking.

---

# Engineering Philosophy

Follow these principles:

1. Implement before redesigning.
2. Prefer the smallest working implementation.
3. Keep modules independently testable.
4. Do not introduce abstractions without a demonstrated need.
5. Do not add microservices.
6. Do not over-engineer the MVP.
7. Use real data as the primary validation mechanism.
8. Write tests around behavior, not implementation details.
9. Preserve traceability from every scholarship back to its official source.
10. If implementation contradicts the specification, investigate the contradiction before changing either one.

---

# Working Style for Hermes

Before making major changes:

1. Inspect the existing repository.
2. Read the relevant specification.
3. Identify what is already implemented.
4. Do not recreate existing components.
5. Make the smallest coherent change.
6. Run relevant tests.
7. Verify behavior against the specification.
8. Only then proceed to the next layer.

Avoid creating large speculative abstractions for future features.

Build the actual product incrementally.

---

# Current Development Step

**Next implementation step:**

1. Perbaiki UI/UX Polaris menjadi platform yang polished:
   * Clean modern scholarship-platform UI/UX.
   * Navigasi jelas antara Discover dan Matching.
   * Scholarship cards dengan score, deadline, funding, country, degree, key requirements.
   * Visual hierarchy untuk Match Score, strengths, gaps, deadline urgency.
   * Scholarship detail experience yang lebih baik.
   * Comparison experience yang berguna.
   * Loading, empty, error, no-match states.
   * Responsive mobile/desktop layout.
   * Clear CTAs ke official applications.
   * Profile form yang mudah & tidak overwhelming.
   * Interface menjelaskan WHY scholarship matches, bukan sekadar score.

2. Setelah UI polished:
   * Lakukan feasibility audit untuk Scholarship Eligibility/Fit Prediction model.
   * Evaluasi data available & labeling strategy.
   * Jangan fabricate performance.

**Jangan implement AI model atau feature lain sebelum UI/UX polished dan feasibility audit selesai.**