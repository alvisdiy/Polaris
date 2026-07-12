# Data Acquisition Strategy

## Polaris — Scholarship Intelligence Platform

**Version:** 0.1
**Owner:** AlVis
**Status:** Draft

---

# Purpose

Dokumen ini menjelaskan bagaimana Polaris memperoleh, memvalidasi, memperbarui, dan mengelola data beasiswa agar tetap akurat, konsisten, dan dapat dipercaya.

Data merupakan aset utama Polaris. Oleh karena itu, kualitas data lebih diprioritaskan daripada kuantitas.

---

# Objectives

* Mengumpulkan data beasiswa dari sumber resmi.
* Menjaga kualitas dan konsistensi data.
* Mengurangi informasi yang tidak valid atau kedaluwarsa.
* Membangun Scholarship Knowledge Base yang dapat digunakan oleh AI Engine.

---

# Data Acquisition Principles

Polaris mengikuti prinsip berikut:

* Official Source First
* Accuracy over Quantity
* Human Verification Before Publication
* Structured Data
* Explainable Data
* Traceable Sources

---

# Source Priority

## Priority 1 — Government

Contoh:

* Ministry of Education
* Ministry of Foreign Affairs
* Embassy
* National Scholarship Agency

Status:

⭐⭐⭐⭐⭐

Selalu diprioritaskan.

---

## Priority 2 — Official University

Contoh:

* Scholarship Office
* Graduate School
* Admission Office

Status:

⭐⭐⭐⭐⭐

---

## Priority 3 — Scholarship Foundation

Contoh:

* Foundation
* NGO
* International Organization

Status:

⭐⭐⭐⭐

---

## Priority 4 — Official Educational Partner

Contoh:

* Mitra resmi universitas
* Mitra resmi pemerintah

Status:

⭐⭐⭐

---

## Priority 5 — Third-party Educational Website

Contoh:

Portal pendidikan.

Status:

⭐⭐

Data hanya digunakan sebagai referensi.

Seluruh informasi tetap harus diverifikasi ke website resmi.

---

## Not Allowed

Data tidak boleh berasal dari:

* Blog pribadi
* Forum
* Reddit
* Facebook
* TikTok
* YouTube
* Thread media sosial

Kecuali hanya sebagai petunjuk menuju sumber resmi.

---

# Data Collection Workflow

```text id="wf73nq"
Official Source

↓

Data Collection

↓

Data Extraction

↓

Data Normalization

↓

Manual Verification

↓

Knowledge Base

↓

Search Engine

↓

AI Engine
```

---

# Collection Method

## Phase 1 (MVP)

Manual Collection

* Copy data dari website resmi.
* Simpan ke format standar.
* Verifikasi satu per satu.

Target:

100–300 beasiswa berkualitas.

---

## Phase 2

Semi Automation

Menggunakan script untuk:

* mendeteksi perubahan,
* mengambil halaman baru,
* mempermudah pembaruan.

Seluruh hasil tetap diverifikasi secara manual.

---

## Phase 3

Automation

Crawler dan pipeline otomatis.

Human verification tetap menjadi langkah terakhir sebelum data dipublikasikan.

---

# Data Extraction Standard

Setiap beasiswa minimal memiliki informasi berikut:

* Nama
* Provider
* Negara
* Universitas
* Jenjang
* Bidang Studi
* Funding
* Persyaratan
* Dokumen
* Deadline
* Website Resmi

Data yang tidak memenuhi standar minimum tidak dipublikasikan.

---

# Data Normalization

Semua data harus dikonversi ke format standar.

Contoh:

## Degree

Tidak boleh:

* Master's
* MSc
* M.S.
* Graduate Program

Semua dinormalisasi menjadi:

Master

---

## Funding

Tidak boleh:

* Full Scholarship
* 100% Funding
* Full Tuition + Living

Dinormalisasi menjadi:

Fully Funded

---

## IELTS

Tidak boleh:

IELTS 6.5 overall band score minimum

Dinormalisasi menjadi:

6.5

---

## Requirement

Tidak boleh:

Research experience is highly preferred.

Dinormalisasi menjadi:

Preferred

---

# Data Validation Checklist

Sebelum data masuk ke database:

* Nama benar.
* URL aktif.
* Deadline valid.
* Funding sesuai.
* Negara benar.
* Persyaratan lengkap.
* Tidak duplikat.
* Memiliki sumber resmi.

---

# Update Strategy

## Deadline

Dicek setiap minggu.

---

## Requirement

Dicek setiap bulan.

---

## Scholarship Baru

Dicari setiap bulan.

---

## Website Tidak Aktif

Langsung masuk daftar review.

---

# Duplicate Detection

Sistem mengecek:

* scholarship_name
* provider
* country
* degree

Jika identik, data tidak dibuat ulang.

---

# Data Quality Metrics

Target kualitas:

| Metric                   | Target |
| ------------------------ | ------ |
| Official Source Coverage | 100%   |
| Duplicate Rate           | < 1%   |
| Missing Field            | < 5%   |
| Invalid URL              | 0%     |
| Outdated Deadline        | < 2%   |

---

# AI Responsibility

AI **tidak bertugas mencari fakta baru**.

AI hanya:

* menjelaskan,
* merangkum,
* membandingkan,
* membantu memahami data yang telah diverifikasi.

Semua fakta tetap berasal dari Scholarship Knowledge Base.

---

# MVP Target

Tahap pertama Polaris menargetkan:

* 100–300 beasiswa berkualitas.
* 10–20 negara tujuan populer.
* Seluruh data berasal dari sumber resmi.
* Seluruh data mengikuti Data Dictionary.

---

# Long-Term Roadmap

Phase 1

Manual Knowledge Base

↓

Phase 2

Semi Automated Data Pipeline

↓

Phase 3

Automated Monitoring

↓

Phase 4

AI-assisted Validation

↓

Phase 5

Global Scholarship Intelligence Network

---

# Success Criteria

Strategi akuisisi data dianggap berhasil apabila:

* Seluruh data memiliki sumber resmi yang dapat diverifikasi.
* Tidak ada data duplikat.
* Deadline selalu diperbarui.
* Data siap digunakan oleh Search Engine dan AI Matching Engine tanpa proses normalisasi tambahan.
