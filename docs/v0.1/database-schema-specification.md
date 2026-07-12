# Database Schema Specification

## Polaris — Scholarship Intelligence Platform

**Version:** 1.0
**Owner:** AlVis
**Status:** Draft
**Last Updated:** July 2026

---

# Purpose

Dokumen ini mendefinisikan struktur database Polaris berdasarkan Data Dictionary.

Tujuannya adalah memastikan seluruh data memiliki relasi yang jelas, mudah dikembangkan, mudah dipelihara, dan mendukung seluruh kebutuhan Scholarship Knowledge Base.

Dokumen ini menjadi acuan implementasi PostgreSQL.

---

# Design Principles

Database mengikuti prinsip berikut:

- Normalized Data
- Single Source of Truth
- Referential Integrity
- Versioned Data
- Official Source First
- Scalable Architecture

---

# High-Level Entity Relationship

```text
Provider ──┐
           │
           ▼
Source Registry ◄──── Country
     │     │
     │     └──────────────┐
     ▼                    ▼
Raw Document          Scholarship
│
├───────────────┐
│               │
▼               ▼
Provider      University
│
▼
Country

Scholarship
│
├───────────────┐
│               │
▼               ▼
Requirement   Benefit

Scholarship
│
▼
Timeline

Scholarship
│
▼
Scholarship Version
```

---

# Core Tables

## source_registry

Menyimpan metadata website resmi untuk aktivitas crawling.

### Columns

| Column Name | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `source_id` | UUID | PRIMARY KEY | `new_uuid()` | Unique source identifier. |
| `source_name` | VARCHAR(255) | NOT NULL | None | Official name of the source registry entry. |
| `country_id` | UUID | FOREIGN KEY REFERENCES `country(country_id)` (ON DELETE RESTRICT) | None | Reference to destination/source country (Nullable). |
| `provider_id` | UUID | FOREIGN KEY REFERENCES `provider(provider_id)` (ON DELETE RESTRICT) | None | Reference to organization provider (Nullable). |
| `official_url` | VARCHAR(2048) | NOT NULL, UNIQUE | None | Base official website homepage URL. |
| `crawl_entry_url` | VARCHAR(2048) | NOT NULL, UNIQUE | None | First page URL targeted for crawler entry. |
| `crawl_method` | VARCHAR(50) | NOT NULL | None | Method of crawling: `'API'`, `'Playwright'`, `'Crawl4AI'`. |
| `connector_name` | VARCHAR(255) | NULLABLE | None | Custom connector name if needed. |
| `crawl_frequency` | VARCHAR(50) | NOT NULL | None | Run frequency: `'Daily'`, `'Weekly'`, `'Monthly'`, `'Manual'`. |
| `priority` | INTEGER | NOT NULL | `3` | Execution priority (1-5, where 1 is highest). |
| `language` | VARCHAR(50) | NULLABLE | None | Main language of the source website. |
| `timezone` | VARCHAR(100) | NULLABLE | None | Timezone of the provider/website. |
| `robots_allowed` | BOOLEAN | NOT NULL | `true` | Crawler respect for robots.txt status. |
| `requires_login` | BOOLEAN | NOT NULL | `false` | Authentication requirement status. |
| `status` | VARCHAR(50) | NOT NULL | `'Active'` | Resource status: `'Active'`, `'Maintenance'`, `'Deprecated'`, `'Blocked'`. |
| `last_crawled_at` | TIMESTAMP WITH TIME ZONE | NULLABLE | None | Timestamp of last crawler run. |
| `last_verified_at` | TIMESTAMP WITH TIME ZONE | NULLABLE | None | Timestamp of last human verification. |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` | Record creation timestamp. |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` | Record update timestamp. |

### Indexes
- Unique index on `official_url` and `crawl_entry_url`.
- Indexes on `country_id` and `provider_id` foreign keys.
- Index on `status`.

---

## raw_document

Menyimpan konten mentah hasil crawling sebelum diproses oleh Knowledge Pipeline.

### Columns

| Column Name | Type | Constraints | Default | Description |
|---|---|---|---|---|
| `document_id` | UUID | PRIMARY KEY | `new_uuid()` | Unique document identifier. |
| `source_id` | UUID | FOREIGN KEY REFERENCES `source_registry(source_id)` (ON DELETE RESTRICT), NOT NULL | None | Reference to source registry. |
| `source_url` | VARCHAR(2048) | NOT NULL | None | Actual URL fetched (may differ from entry URL due to redirects). |
| `content_type` | VARCHAR(50) | NOT NULL | None | Content type: `'html'`, `'pdf'`, `'json'`, `'markdown'`. |
| `raw_content` | TEXT | NOT NULL | None | Raw crawled content (HTML, JSON, etc.). |
| `checksum` | VARCHAR(64) | NOT NULL | None | SHA256 hex digest of `raw_content`. |
| `status_code` | INTEGER | NULLABLE | None | HTTP response status code. |
| `fetched_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | None | Timestamp when content was fetched. |
| `etag` | VARCHAR(255) | NULLABLE | None | HTTP ETag header for conditional fetching. |
| `last_modified` | VARCHAR(255) | NULLABLE | None | HTTP Last-Modified header for conditional fetching. |
| `crawl_duration_ms` | INTEGER | NULLABLE | None | Total crawl duration in milliseconds. |
| `processing_status` | VARCHAR(50) | NOT NULL | `'pending'` | Pipeline status: `'pending'`, `'processing'`, `'completed'`, `'failed'`. |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` | Record creation timestamp. |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` | Record update timestamp. |

### Indexes
- Index on `source_id` foreign key.
- Index on `checksum` for idempotent insert detection.
- Index on `processing_status` for pipeline queue filtering.
- Unique composite index on `(source_id, checksum)` for idempotency.

---

## scholarship

Menyimpan informasi utama beasiswa.

Primary Key

scholarship_id

Foreign Keys

provider_id

country_id

university_id

source_id

---

## provider

Organisasi penyelenggara.

Contoh:

- MEXT
- DAAD
- Fulbright
- Chevening

---

## country

Daftar negara.

---

## university

Daftar universitas.

Digunakan apabila scholarship berasal dari universitas tertentu.

---

## scholarship_requirement

Menyimpan seluruh persyaratan.

Contoh:

- GPA
- IELTS
- TOEFL
- GRE
- Recommendation Letter
- CV

Hubungan:

Scholarship

1

↓

1

Requirement

---

## scholarship_benefit

Contoh:

- Tuition
- Living Allowance
- Insurance
- Travel

---

## scholarship_timeline

Menyimpan:

- Open Date
- Deadline
- Interview
- Result
- Study Start

---

## scholarship_version

Digunakan untuk menyimpan histori perubahan.

Contoh:

Deadline berubah

Funding berubah

Requirement berubah

Tidak menghapus data lama.

---

# Relationship

```text
Country

1

↓

N

Scholarship

-------------------

Provider

1

↓

N

Scholarship

-------------------

University

1

↓

N

Scholarship

-------------------

Source Registry

1

↓

N

Scholarship

-------------------

Scholarship

1

↓

1

Requirement

-------------------

Scholarship

1

↓

1

Benefit

-------------------

Scholarship

1

↓

1

Timeline

-------------------

Scholarship

1

↓

N

Scholarship Version
```

---

# Index Strategy

Index dibuat pada field:

- scholarship_name
- country
- degree
- funding_type
- provider
- application_deadline
- updated_at

Tujuan:

- mempercepat Search
- mempercepat Matching
- mempercepat filtering

---

# Constraints

## Source Registry
- `official_url` dan `crawl_entry_url` harus unik.
- `country_id` dan `provider_id` adalah foreign key nullable.
- Crawler hanya memproses source dengan status `'Active'` dan `robots_allowed = true`.

## Scholarship
Scholarship tidak boleh memiliki:
- source kosong
- provider kosong
- deadline tidak valid

Foreign key wajib aktif.

## General
- Semua foreign key wajib aktif (RESTRICT pada delete).
- Semua UUID primary key menggunakan `new_uuid()` dari `database/utils.py`.
- `created_at` dan `updated_at` menggunakan `TimestampMixin` dari `database/models/base.py`.

---

# Cascade Rules

Delete Provider

↓

Tidak boleh menghapus Scholarship

Delete Source

↓

Tidak boleh menghapus Scholarship

Delete Scholarship

↓

Menghapus:

- Requirement
- Benefit
- Timeline

Tetapi tidak menghapus Version History.

---

# Versioning

Setiap perubahan penting menghasilkan record baru pada:

scholarship_version

Minimal menyimpan:

- Version Number
- Change Type
- Source URL
- Updated At
- Updated By
- Change Summary

---

# Future Expansion

Skema dirancang agar mendukung:

- Fellowship
- Internship
- Research Grant
- Summer School
- Exchange Program

tanpa mengubah struktur inti.

---

# Non Goals

Database tidak melakukan:

- Matching
- AI
- Crawling

Database hanya menyimpan data yang telah tervalidasi.

---

# Success Criteria

Database dianggap berhasil apabila:

- seluruh relasi konsisten,
- tidak ada data duplikat,
- seluruh scholarship memiliki source resmi,
- histori perubahan dapat dilacak,
- performa query tetap baik pada jutaan record.