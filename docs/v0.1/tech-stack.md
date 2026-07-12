# Tech Stack Specification

## Polaris — Scholarship Intelligence Platform

**Version:** 1.0  
**Owner:** AlVis  
**Status:** Approved  
**Last Updated:** July 2026

---

# Purpose

Dokumen ini mendefinisikan seluruh teknologi yang digunakan pada Polaris.

Tujuannya adalah:

- menjaga konsistensi teknologi,
- memudahkan onboarding developer,
- menjadi acuan implementasi,
- menghindari penggunaan library yang tidak diperlukan.

---

# Design Principles

Pemilihan teknologi mengikuti prinsip berikut:

- Stable over Trend
- Open Source First
- Production Ready
- Strong Community
- Long-term Maintainability
- Scalable Architecture

---

# High-Level Stack

```text
Frontend
        │
        ▼
FastAPI Backend
        │
        ▼
Application Services
        │
        ▼
PostgreSQL
```

---

# Programming Language

| Technology | Version |
|------------|---------|
| Python | 3.13 |

Python digunakan sebagai bahasa utama seluruh backend Polaris.

---

# Backend

| Technology | Purpose |
|------------|----------|
| FastAPI | REST API |
| Uvicorn | ASGI Server |

---

# Database

| Technology | Purpose |
|------------|----------|
| PostgreSQL | Primary Database |
| Alembic | Database Migration |
| SQLAlchemy 2 | ORM |

---

# Data Pipeline

| Technology | Purpose |
|------------|----------|
| Playwright | Crawling |
| Crawl4AI | Alternative Crawling |
| Trafilatura | Content Extraction |
| Markdownify | HTML → Markdown |

---

# AI

| Technology | Purpose |
|------------|----------|
| OpenAI GPT-5.5 | Structured Extraction |
| Gemini 2.5 Pro | Alternative LLM |

LLM hanya digunakan untuk ekstraksi dan penjelasan.

LLM **bukan Source of Truth**.

---

# Validation

| Technology | Purpose |
|------------|----------|
| Pydantic v2 | Data Validation |

---

# Scheduler

| Technology | Purpose |
|------------|----------|
| APScheduler | Scheduled Crawling |

---

# Environment

| Technology | Purpose |
|------------|----------|
| python-dotenv | Environment Variables |

---

# Logging

| Technology | Purpose |
|------------|----------|
| Loguru | Logging |

---

# Testing

| Technology | Purpose |
|------------|----------|
| pytest | Unit Testing |

---

# Code Quality

| Technology | Purpose |
|------------|----------|
| Ruff | Linting |
| Black | Formatting |
| isort | Import Sorting |
| mypy | Static Type Checking |

---

# Containerization

| Technology | Purpose |
|------------|----------|
| Docker | Container |
| Docker Compose | Local Development |

---

# Version Control

| Technology | Purpose |
|------------|----------|
| Git | Version Control |
| GitHub | Repository Hosting |

---

# API Documentation

FastAPI otomatis menghasilkan:

- Swagger UI
- OpenAPI Specification

---

# Development Tools

| Tool | Purpose |
|------|----------|
| VS Code | IDE |
| pgAdmin | Database Management |
| Postman / Bruno | API Testing |

---

# Deployment (Future)

- Docker
- Nginx
- GitHub Actions
- VPS / Cloud VM

Future:

- Kubernetes
- Prometheus
- Grafana

---

# Dependency Rules

- Hindari dependency yang tidak diperlukan.
- Seluruh package harus aktif dipelihara.
- Library eksperimen tidak digunakan pada production.

---

# Success Criteria

Tech Stack dianggap berhasil apabila:

- seluruh developer menggunakan stack yang sama,
- seluruh dependency terdokumentasi,
- deployment dapat direplikasi,
- project mudah dipelihara dan dikembangkan.