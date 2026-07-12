# Knowledge Pipeline

## Overview

`knowledge-pipeline` adalah komponen yang bertanggung jawab untuk mengumpulkan, mengekstrak, menormalkan, memvalidasi, dan menyimpan data beasiswa dari sumber resmi ke dalam **Scholarship Knowledge Base**.

Komponen ini merupakan fondasi utama Polaris. Frontend, AI, dan Matching Engine bergantung pada data yang dihasilkan oleh pipeline ini.

---

## Responsibilities

* Mengambil data dari website resmi.
* Membersihkan konten HTML.
* Mengekstrak informasi penting menggunakan AI.
* Menormalkan data sesuai Data Dictionary.
* Memvalidasi hasil ekstraksi.
* Menyimpan data ke Knowledge Base.
* Memperbarui data ketika sumber resmi berubah.

---

## Pipeline Flow

```text
Official Website
        │
        ▼
Crawler

↓

Cleaner

↓

Extractor

↓

Validator

↓

Review Queue

↓

Knowledge Base
```

---

## Folder Structure

```text
knowledge-pipeline/
│
├── crawler/
│   ├── crawl4ai.py
│   ├── playwright.py
│   └── robots.py
│
├── cleaner/
│   ├── html_cleaner.py
│   └── markdown_converter.py
│
├── extractor/
│   ├── llm_extractor.py
│   ├── prompt.py
│   └── schema.py
│
├── validator/
│   ├── pydantic_schema.py
│   └── validate.py
│
├── scheduler/
│   └── scheduler.py
│
├── utils/
│
└── tests/
```

---

## Module Responsibilities

### Crawler

Mengambil halaman dari website resmi menggunakan Crawl4AI atau Playwright.

Output:

* Raw HTML

---

### Cleaner

Membersihkan HTML dengan menghapus elemen yang tidak relevan seperti:

* Navbar
* Footer
* Cookie Banner
* Iklan
* JavaScript yang tidak diperlukan

Output berupa konten yang siap diproses AI.

---

### AI Extractor

Menggunakan Large Language Model untuk mengubah konten menjadi data terstruktur sesuai schema Polaris.

Output:

JSON yang mengikuti Data Dictionary.

---

### Validator

Memastikan seluruh field:

* memiliki tipe data yang benar,
* memenuhi aturan validasi,
* tidak memiliki field wajib yang kosong.

Jika gagal, data tidak diteruskan ke Knowledge Base.

---

### Scheduler

Menjalankan pipeline secara berkala untuk:

* mengecek perubahan deadline,
* mendeteksi halaman baru,
* memperbarui data yang berubah.

---

## Output

Pipeline menghasilkan data JSON yang siap digunakan oleh:

* Scholarship Knowledge Base
* Matching Engine
* AI Scholarship Insight
* Future Analytics

---

## Design Principles

* Official Source First
* Automation with Human Verification
* Structured Data
* Explainable Data
* Modular Pipeline
* Scalable Architecture
* AI as Extractor, Not Source of Truth
