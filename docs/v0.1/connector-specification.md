# Connector Specification

## Polaris — Scholarship Intelligence Platform

**Version:** 1.0
**Owner:** AlVis
**Status:** Draft
**Last Updated:** July 2026

---

# Purpose

Connector merupakan adaptor yang bertanggung jawab mengambil konten dari satu sumber resmi dan mengubahnya menjadi format standar yang dapat diproses oleh Knowledge Pipeline.

Setiap website memiliki struktur HTML yang berbeda.

Oleh karena itu setiap provider memiliki connector sendiri.

---

# Responsibilities

Connector bertugas untuk:

- membuka halaman
- mengambil konten
- membersihkan konten awal
- mengembalikan hasil ke Knowledge Pipeline

Connector tidak melakukan:

- AI Extraction
- Validation
- Matching
- Database Insert

---

# Architecture

```text
Source Registry

↓

Connector Resolver

↓

Connector

↓

Raw Content

↓

Knowledge Pipeline
```

---

# Connector Contract

Semua connector wajib memiliki interface yang sama.

Input

```text
Source Registry Record
```

Output

```text
Raw HTML

atau

Markdown
```

Jika gagal

```text
ConnectorError
```

---

# Folder Structure

```text
connectors/

base_connector.py

government/

mext_connector.py

daad_connector.py

chevening_connector.py

fulbright_connector.py

university/

melbourne_connector.py

oxford_connector.py

mit_connector.py

utils/
```

---

# Connector Lifecycle

```text
Resolve Source

↓

Open Page

↓

Wait Load

↓

Extract Main Content

↓

Return Result
```

---

# Base Connector

Seluruh connector harus mengimplementasikan fungsi berikut.

```python
connect()

fetch()

extract()

close()
```

---

# Supported Content Types

Connector harus mampu menangani:

- HTML
- PDF
- JSON API

Versi berikutnya:

- DOCX
- XML

---

# Error Handling

Connector wajib menangani:

- Timeout
- 403 Forbidden
- 404 Not Found
- 429 Too Many Requests
- SSL Error
- Invalid URL
- JavaScript Rendering Failure

Connector tidak boleh menghentikan seluruh pipeline.

---

# Retry Policy

Maximum Retry

3

Backoff

Exponential

Retry dilakukan hanya pada error yang bersifat sementara.

---

# Logging

Setiap connector wajib mencatat:

- Source ID
- Crawl Time
- Response Status
- Retry Count
- Error Message
- Processing Time

---

# Connector Types

## Playwright Connector

Digunakan untuk website JavaScript.

---

## Crawl4AI Connector

Digunakan untuk website statis.

---

## API Connector

Digunakan apabila tersedia API resmi.

---

## PDF Connector

Digunakan apabila informasi berada pada dokumen PDF.

---

# Custom Connector

Digunakan apabila provider memiliki struktur khusus.

Contoh:

- MEXT
- DAAD
- Fulbright
- Erasmus+
- Chevening

---

# Monitoring Metrics

Setiap connector menghasilkan metric:

- Success Rate
- Failure Rate
- Average Crawl Time
- Retry Count
- Last Success
- Last Failure

---

# Integration

Connector digunakan oleh:

- Scheduler
- Source Registry
- Knowledge Pipeline

Pipeline tidak berinteraksi langsung dengan website.

Seluruh komunikasi dilakukan melalui connector.

---

# Non Goals

Connector tidak bertugas:

- melakukan AI Extraction
- menentukan Match Score
- menyimpan database
- melakukan validasi schema

---

# Success Criteria

Connector dianggap berhasil apabila:

- dapat menangani berbagai tipe website,
- mudah ditambahkan tanpa mengubah pipeline,
- seluruh connector mengikuti interface yang sama,
- kegagalan satu connector tidak menghentikan pipeline,
- provider baru dapat ditambahkan hanya dengan membuat connector baru.