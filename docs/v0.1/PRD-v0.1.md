# Product Requirements Document (PRD) v0.1

**Product Name:** Polaris
**Internal AI Engine:** Scholarship Intelligence Engine (SIE)
**Version:** 0.1
**Owner:** Alvis
**Status:** Draft
**Last Updated:** July 2026

---

# 1. Vision

Polaris membantu pelajar menemukan peluang beasiswa terbaik di seluruh dunia melalui pencarian cerdas, analisis persyaratan, dan rekomendasi berbasis AI yang dapat dijelaskan menggunakan data dari sumber resmi.

---

# 2. Problem Statement

## Current Situation

Informasi beasiswa tersebar di ratusan website resmi pemerintah, universitas, organisasi, dan yayasan. Setiap penyelenggara memiliki format informasi, persyaratan, dan timeline yang berbeda sehingga sulit dipahami oleh calon pendaftar.

## Why This Happens

* Informasi tidak terpusat.
* Persyaratan setiap beasiswa berbeda.
* Sulit membandingkan banyak beasiswa sekaligus.
* Banyak website tidak memiliki fitur pencarian yang baik.
* Calon pendaftar tidak tahu beasiswa mana yang benar-benar sesuai dengan profil mereka.

## Impact

Akibatnya banyak mahasiswa:

* Menghabiskan waktu berjam-jam mencari informasi.
* Terlambat mengetahui deadline.
* Salah memilih beasiswa.
* Menyerah sebelum mendaftar karena proses terasa rumit.

---

# 3. Vision of Success

Dalam waktu kurang dari **5 menit**, seorang mahasiswa dapat menemukan beberapa beasiswa yang benar-benar relevan dengan kebutuhannya tanpa harus membuka puluhan website.

---

# 4. Target User

## Primary User

Mahasiswa Indonesia

* Usia 19–25 tahun
* Sedang menempuh S1
* Memiliki rencana melanjutkan studi S2 di luar negeri
* Belum mengetahui beasiswa yang sesuai

### Pain Points

* Bingung harus mulai dari mana.
* Tidak tahu beasiswa yang cocok.
* Sulit memahami persyaratan.
* Sulit membandingkan berbagai pilihan.

---

# 5. Core Value

Polaris bukan sekadar mesin pencari beasiswa.

Polaris membantu pengguna:

* menemukan peluang yang paling relevan,
* memahami alasan mengapa peluang tersebut direkomendasikan,
* membandingkan berbagai pilihan,
* memahami seluruh persyaratan dengan cepat,
* langsung menuju sumber resmi untuk melakukan pendaftaran.

---

# 6. Product Positioning

**Polaris adalah Scholarship Intelligence Platform, bukan sekadar Scholarship Database.**

Google memberikan ribuan hasil pencarian.

Polaris memberikan jawaban yang telah dianalisis.

---

# 7. Goals

## Business Goal

Membangun platform yang menjadi referensi utama pencarian beasiswa global.

## User Goal

Pengguna dapat menemukan beasiswa yang sesuai dengan profil dan tujuan studinya secara cepat dan mudah.

---
# 8. MVP Scope (Version 1)

## Feature 1 — Smart Profile Assessment

### Description

Pengguna mengisi profil akademik dan preferensi studi melalui form terstruktur.

### User Can

* memilih negara tujuan
* memilih jenjang studi
* memilih bidang studi
* memasukkan IPK
* memasukkan skor IELTS/TOEFL (opsional)
* mengisi pengalaman penelitian
* mengisi pengalaman organisasi
* memilih preferensi pendanaan

Output dari fitur ini adalah profil pengguna yang akan diproses oleh Scholarship Intelligence Engine (SIE).

---

## Feature 2 — Scholarship Intelligence Engine (SIE)

### Description

Scholarship Intelligence Engine (SIE) melakukan pencocokan antara profil pengguna dan Scholarship Knowledge Base menggunakan algoritma filtering, weighted scoring, dan ranking.

### User Can

* mendapatkan daftar beasiswa yang paling relevan
* melihat Match Score setiap beasiswa
* mengetahui alasan mengapa beasiswa direkomendasikan

Seluruh perhitungan dilakukan oleh Matching Engine tanpa bantuan Large Language Model (LLM).

---

## Feature 3 — AI Scholarship Insight

### Description

AI membantu pengguna memahami hasil rekomendasi yang telah dihitung oleh Scholarship Intelligence Engine.

LLM hanya menerima hasil dari Matching Engine, kemudian menghasilkan penjelasan dalam bahasa yang mudah dipahami.

### AI Menjelaskan

* alasan beasiswa direkomendasikan
* persyaratan yang sudah dipenuhi
* persyaratan yang masih kurang
* langkah berikutnya yang dapat dilakukan pengguna

AI tidak menentukan Match Score dan tidak membuat fakta baru di luar Scholarship Knowledge Base.

---

## Feature 4 — Scholarship Compare

### Description

Pengguna dapat membandingkan beberapa beasiswa dalam satu halaman.

### User Can

Membandingkan:

* pendanaan
* persyaratan
* skor bahasa
* deadline
* benefit
* dokumen
* website resmi

---

## Feature 5 — Official Source Aggregation

### Description

Seluruh informasi beasiswa berasal dari sumber resmi.

Setiap scholarship wajib memiliki:

* Website resmi
* Halaman pendaftaran resmi
* Dokumen resmi (jika tersedia)

Polaris tidak menggunakan blog atau sumber tidak resmi sebagai sumber utama informasi.

---

# 9. User Flow

```text
Landing Page
      │
      ▼
Smart Profile Assessment
      │
      ▼
Input Validation
      │
      ▼
Scholarship Matching Engine
      │
      ▼
Weighted Scoring
      │
      ▼
Ranking
      │
      ▼
AI Scholarship Insight
      │
      ▼
Scholarship Compare (Optional)
      │
      ▼
Official Scholarship Detail
      │
      ▼
Official Website
      │
      ▼
Apply
```

---

# 10. AI Workflow

```text
User Profile
      │
      ▼
Input Validation
      │
      ▼
Profile Normalization
      │
      ▼
Scholarship Filtering
      │
      ▼
Weighted Scoring
      │
      ▼
Ranking Engine
      │
      ▼
Gap Analysis
      │
      ▼
LLM Explanation
      │
      ▼
Final Recommendation
```

---
# 15. Operational Requirements

Untuk menjaga kualitas Scholarship Knowledge Base, Polaris menetapkan beberapa requirement operasional yang harus dipenuhi sebelum data dipublikasikan.

## 15.1 Official Source Registry

Seluruh website yang menjadi sumber data harus terdaftar dalam **Source Registry**.

Source Registry berfungsi sebagai pusat konfigurasi Knowledge Pipeline.

Minimal setiap sumber memiliki informasi berikut:

- Source ID
- Provider Name
- Official Website
- Country
- Source Category
- Crawl Frequency
- Crawl Method
- Status
- Last Crawl Time
- Last Verification Time

Crawler hanya diperbolehkan mengambil data dari Source Registry.

Website yang tidak terdaftar tidak boleh diproses oleh Knowledge Pipeline.

---

## 15.2 Opportunity-first Data Model

Walaupun MVP hanya berfokus pada Scholarship, struktur data Polaris dirancang menggunakan konsep **Opportunity**.

Opportunity merupakan entitas induk yang memungkinkan ekspansi tanpa perubahan arsitektur besar.

Opportunity dapat mencakup:

- Scholarship
- Fellowship
- Internship
- Research Grant
- Summer School
- Exchange Program
- Competition
- Conference Funding

Pada versi pertama hanya tipe **Scholarship** yang diaktifkan.

---

## 15.3 Crawl Policy

Knowledge Pipeline wajib mengikuti kebijakan crawling yang bertanggung jawab.

Crawler harus:

- menghormati robots.txt apabila berlaku,
- menggunakan rate limiting,
- menerapkan retry mechanism,
- menggunakan exponential backoff ketika terjadi kegagalan,
- mencatat seluruh aktivitas crawling,
- tidak melakukan crawling berlebihan terhadap website resmi.

Tujuannya adalah menjaga kestabilan pipeline dan menghindari pemblokiran oleh penyedia data.

---

## 15.4 Data Versioning

Perubahan informasi beasiswa tidak boleh langsung menghapus data sebelumnya.

Knowledge Base harus mampu menyimpan histori perubahan penting, seperti:

- deadline,
- persyaratan,
- benefit,
- funding,
- eligibility.

Setiap perubahan wajib memiliki:

- Version Number
- Updated At
- Source URL
- Change Summary

Versioning memungkinkan Polaris melakukan audit data dan mendeteksi perubahan dari sumber resmi.

---

## 15.5 Human Review Workflow

AI bukan Source of Truth.

Seluruh hasil ekstraksi AI wajib melalui proses validasi sebelum dipublikasikan.

Workflow publikasi data:

Official Website

↓

Crawler

↓

Content Cleaner

↓

AI Extraction

↓

Schema Validation

↓

Human Review

↓

Knowledge Base

↓

Search Engine

↓

Matching Engine

↓

AI Scholarship Insight

Data yang gagal validasi tidak boleh dipublikasikan.

---

## Success Criteria

Operational Layer dianggap berhasil apabila:

- seluruh data memiliki sumber resmi,
- seluruh website berasal dari Source Registry,
- seluruh perubahan memiliki histori versi,
- crawler berjalan sesuai Crawl Policy,
- AI tidak dapat mempublikasikan data tanpa proses validasi,
- Knowledge Base selalu dapat ditelusuri kembali ke sumber resmi.


# 16. Future Vision (Not in MVP)

Beberapa fitur yang direncanakan setelah MVP:

* Natural Language Search
* AI Scholarship Recommendation
* Personalized Scholarship Timeline
* Deadline Reminder
* AI Essay Review
* AI Interview Practice
* Scholarship Tracker
* User Dashboard
* Scholarship API
* Mobile Application
* Community & Mentor Network

MVP fokus Scholarship, tetapi fondasi data menggunakan konsep Opportunity agar mudah dikembangkan ke Fellowship, Internship, Summer School, Research Grant, dan lainnya di masa depan.

---

# MVP Definition

Polaris v1 dianggap selesai apabila pengguna dapat:

1. Mengisi profil akademik dan preferensi studi.
2. Mendapatkan rekomendasi beasiswa berdasarkan Scholarship Intelligence Engine.
3. Memahami alasan rekomendasi melalui AI Scholarship Insight.
4. Membandingkan beberapa beasiswa.
5. Mengakses website resmi untuk melakukan pendaftaran.
