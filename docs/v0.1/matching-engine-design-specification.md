# Matching Engine Design Specification

## Polaris — Scholarship Intelligence Engine (SIE)

**Version:** 0.1
**Owner:** AlVis
**Status:** Draft

---

# Purpose

Dokumen ini mendefinisikan bagaimana Scholarship Intelligence Engine (SIE) menganalisis profil pengguna dan menghasilkan rekomendasi beasiswa yang relevan, transparan, dan dapat dijelaskan.

Engine harus menghasilkan rekomendasi yang:

* konsisten,
* dapat dijelaskan (Explainable AI),
* tidak bergantung pada LLM untuk mengambil keputusan.

LLM hanya bertugas menjelaskan hasil yang telah dihitung oleh engine.

---

# Design Principles

SIE dibangun berdasarkan prinsip berikut:

* Explainable Recommendation
* Deterministic Scoring
* Official Data Only
* Human Understandable Result
* AI as Assistant, Not Decision Maker

---

# High Level Flow

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
Matching Engine
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
Recommendation
```

---

# User Profile

Data yang digunakan:

* Target Country
* Degree
* Field of Study
* Current GPA
* IELTS
* TOEFL
* Research Experience
* Work Experience
* Publication
* Leadership
* Funding Preference

---

# Step 1 — Input Validation

Validasi dasar.

Contoh:

* GPA berada pada rentang 0–4.
* IELTS berada pada rentang 0–9.
* Negara valid.
* Degree valid.

Jika tidak valid, sistem meminta pengguna memperbaiki input.

---

# Step 2 — Profile Normalization

Seluruh input dikonversi ke format standar.

Contoh:

Master's → Master

AI → Artificial Intelligence

Computer Eng → Computer Engineering

Research:
Yes / No

Funding:
Fully Funded / Partial

---

# Step 3 — Scholarship Filtering

Sebelum dilakukan scoring, engine menghapus scholarship yang jelas tidak sesuai.

Contoh:

* Degree tidak sesuai.
* Negara tidak sesuai (jika user memilih negara tertentu).
* Scholarship sudah ditutup.
* Jurusan tidak tersedia.

Filtering bertujuan mengurangi ruang pencarian.

---

# Step 4 — Matching Engine

Setiap scholarship dibandingkan dengan profil pengguna.

## Matching Criteria

| Criteria            | Weight |
| ------------------- | -----: |
| Country             |     20 |
| Degree              |     20 |
| Field of Study      |     20 |
| GPA                 |     15 |
| Language            |     10 |
| Funding Preference  |      5 |
| Research Experience |      5 |
| Work Experience     |      3 |
| Leadership          |      2 |

Total Weight = 100

Catatan:
Bobot ini merupakan versi awal dan dapat berubah berdasarkan hasil evaluasi serta feedback pengguna.

---

# Step 5 — Score Calculation

Setiap kriteria menghasilkan skor parsial.

Contoh:

Country Match

20 / 20

Degree Match

20 / 20

Major Match

18 / 20

GPA Match

15 / 15

Language Match

8 / 10

Research Match

2 / 5

Leadership

1 / 2

Total Score

84 / 100

---

# Step 6 — Ranking Engine

Scholarship diurutkan berdasarkan:

1. Match Score
2. Deadline terdekat
3. Funding Type
4. Data Completeness

Hasil akhir berupa Top-N recommendation.

Default:

Top 10

---

# Step 7 — Gap Analysis

Gap Analysis mengidentifikasi perbedaan antara profil pengguna dan requirement scholarship.

Contoh:

Scholarship

MEXT

Requirement

IELTS 6.5

User

IELTS 6.0

Gap

0.5

---

Research

Preferred

User

None

Gap

Need Research Experience

---

# Step 8 — Explainable Recommendation

LLM menerima:

* Match Score
* Requirement
* Gap
* Benefits
* Timeline

LLM menghasilkan penjelasan.

Contoh:

"MEXT direkomendasikan karena program ini sesuai dengan bidang studi dan target negara Anda. Persyaratan akademik telah terpenuhi, namun pengalaman riset masih menjadi aspek yang perlu ditingkatkan."

LLM tidak boleh:

* mengubah skor,
* menambah fakta,
* membuat persyaratan baru.

---

# Recommendation Categories

| Score  | Category        |
| ------ | --------------- |
| 90–100 | Excellent Match |
| 80–89  | Strong Match    |
| 70–79  | Good Match      |
| 60–69  | Moderate Match  |
| <60    | Low Match       |

---

# Response Object

Setiap rekomendasi minimal berisi:

* Scholarship Name
* Match Score
* Recommendation Category
* Key Strengths
* Missing Requirements
* Official Link

---

# Explainability Rules

Semua rekomendasi harus menjawab:

* Mengapa scholarship ini muncul?
* Persyaratan apa yang sudah dipenuhi?
* Apa yang masih kurang?
* Apa langkah berikutnya?

Pengguna tidak boleh menerima skor tanpa penjelasan.

---

# Future Improvements

Versi berikutnya dapat menambahkan:

* Machine Learning Ranking
* Recommendation System berbasis histori pengguna
* Personalized Weight Adjustment
* Learning-to-Rank Model
* Feedback Loop
* AI Preference Learning

---

# Non Goals

Versi pertama Matching Engine tidak akan:

* memprediksi peluang diterima,
* menjamin kelulusan,
* menggantikan keputusan penyelenggara beasiswa,
* menggunakan data yang tidak berasal dari sumber resmi.

---

# Success Criteria

Matching Engine dianggap berhasil apabila:

* menghasilkan rekomendasi yang konsisten,
* seluruh skor dapat dijelaskan,
* pengguna memahami alasan rekomendasi,
* hasil berasal dari data resmi,
* proses pencarian selesai dalam waktu singkat.
