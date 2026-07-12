# Engineering Decisions (Architecture Decision Record)

## Polaris — Scholarship Intelligence Platform

**Version:** 1.0  
**Owner:** AlVis  
**Status:** Approved  
**Last Updated:** July 2026

---

# Purpose

Dokumen ini mencatat keputusan-keputusan teknis utama selama pengembangan Polaris beserta alasan di balik keputusan tersebut.

Tujuannya adalah:

- mendokumentasikan alasan pemilihan teknologi,
- mempermudah evaluasi di masa depan,
- menjaga konsistensi engineering.

---

# ADR-001

## Decision

Menggunakan **Modular Monolith**.

### Alternatives

- Microservices
- Monolithic MVC

### Reason

- lebih sederhana,
- lebih cepat dikembangkan,
- mudah dipecah menjadi microservices di masa depan,
- cocok untuk MVP.

---

# ADR-002

## Decision

Menggunakan **FastAPI**.

### Alternatives

- Django
- Flask

### Reason

- asynchronous,
- performa tinggi,
- OpenAPI otomatis,
- type hint native.

---

# ADR-003

## Decision

Menggunakan **PostgreSQL**.

### Alternatives

- MySQL
- MongoDB

### Reason

- relational,
- JSONB support,
- indexing kuat,
- production proven.

---

# ADR-004

## Decision

Menggunakan **SQLAlchemy 2**.

### Alternatives

- Tortoise ORM
- Django ORM

### Reason

- mature,
- fleksibel,
- banyak digunakan.

---

# ADR-005

## Decision

Menggunakan **Playwright** sebagai crawler utama.

### Alternatives

- Selenium
- BeautifulSoup
- Scrapy

### Reason

- mendukung JavaScript,
- stabil,
- cepat,
- modern.

---

# ADR-006

## Decision

Menggunakan **Trafilatura**.

### Alternatives

- BeautifulSoup
- Readability

### Reason

- ekstraksi konten utama lebih akurat,
- mengurangi noise HTML.

---

# ADR-007

## Decision

Menggunakan **Connector Pattern**.

### Alternatives

- Satu crawler universal

### Reason

- setiap website memiliki struktur berbeda,
- mudah menambah provider,
- tidak memenuhi kode dengan if-else.

---

# ADR-008

## Decision

Menggunakan **Source Registry**.

### Alternatives

- Hardcoded URL

### Reason

- mudah menambah source,
- konfigurasi terpusat,
- scheduler lebih sederhana.

---

# ADR-009

## Decision

Menggunakan **Scholarship Knowledge Base**.

### Alternatives

- Crawling real-time

### Reason

- lebih cepat,
- lebih stabil,
- AI tidak bergantung pada website eksternal.

---

# ADR-010

## Decision

LLM bukan Source of Truth.

### Reason

AI hanya:

- mengekstrak,
- merangkum,
- menjelaskan.

AI tidak:

- menentukan Match Score,
- membuat fakta,
- mengubah data resmi.

---

# ADR-011

## Decision

Menggunakan **Deterministic Matching Engine**.

### Alternatives

- Full AI Recommendation

### Reason

- hasil konsisten,
- mudah dijelaskan,
- mudah diuji,
- transparan.

---

# ADR-012

## Decision

Human Review sebelum Publish.

### Reason

Seluruh data AI harus diverifikasi sebelum masuk Scholarship Knowledge Base.

---

# ADR-013

## Decision

Opportunity-first Architecture.

### Reason

MVP hanya Scholarship.

Namun fondasi harus mampu berkembang menjadi:

- Fellowship
- Internship
- Research Grant
- Summer School
- Exchange Program

tanpa perubahan arsitektur besar.

---

# ADR-014

## Decision

Documentation Freeze setelah Architecture v1.0.

### Reason

Menghindari analysis paralysis.

Perubahan besar hanya dilakukan berdasarkan hasil implementasi nyata.

---

# Future ADR

Keputusan baru harus ditambahkan sebagai ADR baru.

ADR lama tidak diubah agar histori keputusan tetap terjaga.

---

# ADR Backlog

Keputusan yang ditunda untuk diimplementasi di masa depan:

| # | Topic | Description | Trigger |
|---|-------|-------------|---------|
| ADR-B-001 | Object Storage | Move raw_content to S3/MinIO, keep path in DB | When raw_document volume exceeds 100 GB |
| ADR-B-002 | Binary Storage | Store PDF/binaries in object storage, not TEXT column | When PDF crawling is implemented |
| ADR-B-003 | JSONB Metadata | Add JSONB column for flexible crawl metadata | When connector diversity requires per-source metadata |
| ADR-B-004 | Checksum Algorithm | Revisit SHA256 choice if performance becomes a bottleneck | When checksumming becomes a measurable overhead |
| ADR-B-005 | Richer Lifecycle | Add archived/retention lifecycle to raw_document | When document retention policy is defined |

---

# Success Criteria

Engineering Decision dianggap berhasil apabila:

- seluruh keputusan teknis terdokumentasi,
- alasan pemilihan teknologi jelas,
- developer baru dapat memahami arsitektur,
- perubahan teknologi dapat dievaluasi secara historis.