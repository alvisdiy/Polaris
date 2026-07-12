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
Source Registry
        │
        │
        ▼
Scholarship
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

Menyimpan metadata website resmi.

Primary Key

source_id

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

Semua URL harus unik.

Scholarship tidak boleh memiliki:

- source kosong
- provider kosong
- deadline tidak valid

Foreign key wajib aktif.

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