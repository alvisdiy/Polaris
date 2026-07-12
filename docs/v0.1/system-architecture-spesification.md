# System Architecture Specification

## Polaris — Scholarship Intelligence Platform

**Version:** 0.1
**Owner:** AlVis
**Status:** Draft

---

# Purpose

Dokumen ini menjelaskan arsitektur sistem Polaris secara keseluruhan, hubungan antar komponen, serta tanggung jawab masing-masing modul.

Tujuan utama arsitektur adalah:

* Modular
* Mudah dikembangkan
* Mudah diuji
* Mudah di-scale
* AI tidak bergantung langsung pada database

---

# Architecture Principles

Polaris dibangun berdasarkan prinsip berikut:

* Modular Architecture
* Separation of Concerns
* AI as Service
* Official Data First
* Explainable Recommendation

---

# High Level Architecture

```text
                User
                  │
                  ▼
          Frontend (Web)
                  │
                  ▼
           Backend API
                  │
 ┌────────────────┼────────────────┐
 │                │                │
 ▼                ▼                ▼
Search       Matching Engine     AI Engine
 │                │                │
 └────────────────┼────────────────┘
                  ▼
        Scholarship Database
                  │
                  ▼
       Official Source Metadata
```

---

# Core Components

## 1. Frontend

Tanggung jawab:

* Landing Page
* Search
* Result Page
* Scholarship Detail
* Compare
* Profile Form

Frontend **tidak menghitung rekomendasi**.

Frontend hanya menampilkan data.

---

## 2. Backend API

Tanggung jawab:

* Validasi request
* Menghubungkan frontend
* Mengatur business logic
* Memanggil Matching Engine
* Memanggil AI Engine

Backend menjadi "orchestrator".

---

## 3. Scholarship Database

Menyimpan:

* Scholarship
* Requirement
* Benefits
* Timeline
* Provider
* Country
* University

Tidak ada logika AI di database.

---

## 4. Matching Engine

Input:

Profil pengguna

Output:

Daftar scholarship + Match Score

Matching Engine menggunakan:

* Filtering
* Weighted Scoring
* Ranking

---

## 5. AI Engine

Input:

Hasil Matching Engine

Output:

Penjelasan dalam bahasa alami.

AI tidak melakukan pencarian data langsung.

AI tidak membuat fakta baru.

---

# Request Flow

```text
User

↓

Search Form

↓

Backend API

↓

Matching Engine

↓

Scholarship Database

↓

Match Result

↓

AI Engine

↓

Explanation

↓

Frontend
```

---

# Internal Modules

```text
backend/

├── api/
├── services/
├── matching/
├── ai/
├── database/
├── models/
├── repositories/
├── utils/
└── config/
```

---

# AI Responsibilities

AI hanya bertugas:

* Menjelaskan rekomendasi
* Merangkum requirement
* Membandingkan scholarship
* Membantu pengguna memahami hasil

AI tidak boleh:

* Mengubah Match Score
* Mengarang requirement
* Menghasilkan link baru
* Menambahkan informasi tanpa sumber resmi

---

# Database Responsibilities

Database bertanggung jawab atas:

* Konsistensi data
* Integritas data
* Relasi data
* Riwayat pembaruan

---

# Future Services

Belum digunakan pada MVP.

* Authentication Service
* Notification Service
* Analytics Service
* Recommendation Learning
* Admin Dashboard
* Monitoring Service

---

# Non Functional Requirements

## Performance

* Hasil pencarian < 3 detik
* Matching < 2 detik
* AI Insight < 5 detik

---

## Reliability

* Official source coverage 100%
* Tidak ada data duplikat
* AI selalu memiliki sumber data

---

## Scalability

Arsitektur harus memungkinkan:

* Penambahan negara baru
* Penambahan provider baru
* Penambahan AI Model
* Penambahan Mobile App

tanpa mengubah core architecture.

---

# Success Criteria

Arsitektur dianggap berhasil apabila:

* Setiap modul memiliki tanggung jawab yang jelas.
* AI dapat diganti tanpa mengubah Matching Engine.
* Database dapat berkembang tanpa memengaruhi Frontend.
* Sistem mudah dikembangkan menjadi platform berskala global.
