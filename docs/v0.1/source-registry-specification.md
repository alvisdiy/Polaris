# Source Registry Specification

## Polaris — Scholarship Intelligence Platform

**Version:** 1.0  
**Owner:** AlVis  
**Status:** Draft  
**Last Updated:** July 2026

---

# Purpose

Source Registry merupakan katalog seluruh sumber data resmi yang digunakan oleh Polaris.

Source Registry menjadi **single source of truth** bagi Knowledge Pipeline untuk menentukan:

- website yang boleh dicrawl,
- metode crawling,
- frekuensi pembaruan,
- prioritas sumber,
- status sumber,
- metadata kualitas sumber.

Crawler **tidak diperbolehkan** melakukan crawling terhadap website yang tidak terdaftar pada Source Registry.

---

# Design Goals

Source Registry dirancang agar:

- mudah ditambah tanpa mengubah kode crawler,
- mudah dikelola,
- dapat diaudit,
- scalable hingga ribuan sumber,
- mendukung berbagai metode pengambilan data.

---

# Responsibilities

Source Registry bertanggung jawab untuk:

- menyimpan daftar website resmi,
- menentukan metode crawling,
- menentukan jadwal crawling,
- menyimpan metadata sumber,
- membantu monitoring kualitas data,
- menjadi referensi utama Knowledge Pipeline.

---

# Registry Flow

```text
Administrator

↓

Register New Source

↓

Source Registry

↓

Knowledge Pipeline

↓

Crawler

↓

Knowledge Base
```

---

# Main Entity

Setiap sumber data direpresentasikan sebagai satu record.

| Field | Type | Required | Description |
|--------|------|----------|-------------|
| source_id | UUID | ✅ | Unique identifier |
| source_name | String(255) | ✅ | Official source name |
| country_id | UUID (FK) | ❌ | Reference to Country table |
| provider_id | UUID (FK) | ❌ | Reference to Provider table |
| official_url | String(2048) | ✅ | Root website |
| crawl_entry_url | String(2048) | ✅ | First page to crawl |
| crawl_method | String(50) | ✅ | API, Playwright, Crawl4AI |
| connector_name | String(255) | ❌ | Custom connector |
| crawl_frequency | String(50) | ✅ | Daily, Weekly, Monthly |
| priority | Integer | ✅ | Crawl priority (1-5) |
| language | String(50) | ❌ | Source language |
| timezone | String(100) | ❌ | Timezone |
| robots_allowed | Boolean | ✅ | robots.txt status |
| requires_login | Boolean | ✅ | Authentication required |
| status | String(50) | ✅ | Active, Maintenance, Deprecated, Blocked |
| last_crawled_at | Timestamp | ❌ | Last crawl |
| last_verified_at | Timestamp | ❌ | Human verification |
| created_at | Timestamp | ✅ | Creation time |
| updated_at | Timestamp | ✅ | Last update |

---

# Source Categories

Priority ditentukan berdasarkan tingkat kepercayaan.

| Priority | Source |
|----------|--------|
| P1 | Government |
| P1 | Embassy |
| P1 | National Scholarship Agency |
| P2 | Official University |
| P3 | Foundation |
| P3 | International Organization |
| P4 | Official Educational Partner |
| P5 | Trusted Educational Portal |

Blog pribadi, forum, media sosial, dan website tidak resmi tidak boleh didaftarkan sebagai Source Registry.

---

# Crawl Methods

Source Registry mendukung beberapa metode crawling.

## API

Digunakan apabila penyedia menyediakan API resmi.

Contoh:

- REST API
- GraphQL

---

## Playwright

Digunakan untuk website dengan JavaScript rendering.

---

## Crawl4AI

Digunakan untuk website statis maupun semi-dinamis yang membutuhkan ekstraksi konten.

---

## Custom Connector

Digunakan apabila website memiliki struktur khusus yang membutuhkan parser khusus.

Contoh:

- MEXT
- DAAD
- Chevening

---

# Crawl Frequency

| Value | Description |
|--------|-------------|
| Daily | Perubahan sangat sering |
| Weekly | Deadline berubah berkala |
| Monthly | Informasi relatif stabil |
| Manual | Hanya dijalankan manual |

---

# Source Status

| Status | Description |
|--------|-------------|
| Active | Dapat dicrawl |
| Maintenance | Sementara dihentikan |
| Deprecated | Tidak lagi digunakan |
| Blocked | Diblokir sementara |

Crawler hanya memproses source dengan status **Active**.

---

# Quality Score

Setiap source memiliki skor kualitas.

| Metric | Weight |
|---------|------:|
| Official Source | 40 |
| Data Completeness | 20 |
| Data Freshness | 20 |
| Crawl Stability | 10 |
| Validation Success | 10 |

Maximum Score = 100

Source dengan Quality Score rendah dapat ditandai untuk review.

---

# Validation Rules

Sebelum source dapat digunakan:

- official_url harus valid,
- crawl_entry_url harus dapat diakses,
- crawl_method harus didukung,
- priority harus tersedia,
- status harus Active.

Source yang gagal validasi tidak boleh digunakan oleh crawler.

---

# Connector Resolution

Knowledge Pipeline menentukan connector berdasarkan `crawl_method`.

Contoh:

```text
Playwright

↓

Default Playwright Connector

----------------------------

Custom Connector

↓

connectors/mext.py

----------------------------

API

↓

api_connector.py
```

---

# Example Record

```json
{
  "source_id": "d3b07384-d113-4956-be64-6df457c12345",
  "source_name": "Study in Japan",
  "country_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  "provider_id": "f8e7d6c5-b4a3-2f1e-0d9c-8b7a6f5e4d3c",
  "official_url": "https://www.studyinjapan.go.jp/",
  "crawl_entry_url": "https://www.studyinjapan.go.jp/en/",
  "crawl_method": "Playwright",
  "connector_name": "mext_connector",
  "crawl_frequency": "Monthly",
  "priority": 1,
  "robots_allowed": true,
  "requires_login": false,
  "status": "Active"
}
```

---

# Integration

Source Registry digunakan oleh:

- Knowledge Pipeline
- Scheduler
- Crawler
- Monitoring Service
- Admin Dashboard (Future)

---

# Non Goals

Source Registry tidak bertugas untuk:

- menyimpan data beasiswa,
- menyimpan hasil ekstraksi AI,
- melakukan pencocokan beasiswa,
- menghasilkan rekomendasi.

Source Registry hanya mengelola metadata sumber data.

---

# Future Improvements

Versi berikutnya dapat menambahkan:

- Automatic Source Discovery
- Source Health Monitoring
- Crawl Analytics
- Crawl Cost Estimation
- Source Reputation Scoring
- Multi-region Crawling

---

# Success Criteria

Source Registry dianggap berhasil apabila:

- seluruh sumber data Polaris terdaftar,
- crawler hanya menggunakan source yang terdaftar,
- setiap source memiliki metadata lengkap,
- jadwal crawling dapat dikontrol tanpa mengubah kode,
- penambahan source baru tidak memerlukan perubahan pada core crawler,
- seluruh data dapat ditelusuri kembali ke sumber resminya.