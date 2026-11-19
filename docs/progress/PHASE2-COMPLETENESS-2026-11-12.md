# Fase 2 — Kelengkapan Data & Identitas Provider — 12 November 2026

Rencana awal punya fase scheduler; itu dicoret atas permintaan (pipeline dijalankan
manual). Yang dikerjakan: **Fase 2** — deadline, funding, dan identitas provider.

---

## 1. Deadline: extractor-nya buta pada bahasa sendiri

Sebelumnya 26 dari 130 record punya deadline. Setelah diperiksa, 30 halaman
**mencantumkan** deadline dengan bentuk yang tidak dikenali:

| Bentuk di halaman | Status sebelumnya |
|---|---|
| `The deadline for applications is the 5 June 2027` | gagal — "for applications" bukan filler |
| `The deadline to apply is 3 May 2027` | gagal — "apply" tidak ada di filler |
| `deadline for submitting application materials for the program is December 15, 2026 at 23:59` | gagal — jarak > 60 karakter |
| `new deadline in May (update: 28/04/2026)` | gagal — tidak ada pola `DD/MM/YYYY` |
| `The nomination deadline is 23:59 on Wednesday, Oktober 8, 2025` | gagal — jam tanpa am/pm dan bulan "Oktober" |
| `Tarikh tutup permohonan: 31 Disember 2026` | gagal — kata kunci Melayu tidak ada |
| `Bewerbungsschluss: 15. März 2027` | gagal — "ä" bukan `[A-Za-z]` |

Yang diperbaiki:

1. **Filler diperluas** dengan kata yang memang muncul di antara "deadline" dan
   tanggal: `applications`, `applying`, `apply`, `submitting`, `materials`,
   `program`, `course`, `update`, plus jam `23:59` tanpa am/pm.
2. **Kata kunci multilingual**: `tarikh tutup`, `tempoh permohonan`,
   `permohonan tutup`, `bewerbungsschluss`, `bewerbungsfrist`, `anmeldeschluss`.
3. **Nama bulan non-Inggris**: Januari…Desember, Disember, Januar…Dezember,
   März — dinormalisasi sebelum parsing.
4. **`DD/MM/YYYY`** dengan aturan tegas: hari > 12 → day-first, bulan > 12 →
   month-first, **selain itu ditolak** (03/04/2026 adalah dua hari berbeda
   tergantung negara penulis).
5. **Batas jarak** dinaikkan 60 → 90 karakter, tapi filler tetap kosakata
   tertutup — sehingga "deadline, i.e. have defended their PhD thesis between
   December 2021" tetap bukan deadline (ada test-nya).

Hasil: **deadline 26 → 42** (dari 130 → 139 approved setelah auto-review).
Sisa 97 record tanpa deadline memang tidak mencantumkan tanggal di halamannya.

---

## 2. Degree: inference dari bukti

- Name/URL inference (`degree_fallback`) mengisi level saat buktinya tunggal.
- `degree_levels` untuk halaman yang menyebut beberapa level.
- Hasil: **degree 99 → 106**.

---

## 3. Provider identity tanpa menebak

`scripts/fix_provider_identity.py` mengganti nama provider yang masih berupa
hostname dengan nama institusi **dari halamannya sendiri**:

| Bukti | Contoh |
|---|---|
| JSON-LD `Organization`/`CollegeOrUniversity` | `upm.edu.my` → Universiti Putra Malaysia |
| `og:site_name` | `deutschlandstipendium.de` → Bundesministerium für Bildung und Forschung |
| Judul halaman + kata institusi | `mara.gov.my` → Majlis Amanah Rakyat, `um.edu.my` → Universiti Malaya, `mohe.gov.my` → Kementerian Pendidikan Tinggi |

Aturan: hanya menerima nama yang mengandung kata institusi (University,
Kementerian, Majlis, Ministry, College, …) atau berasal dari JSON-LD; judul
artikel seperti "Financial Aid, Scholarships, & Tuition" tidak dipakai.

Efek: hold `provider_identity` turun dari 12 → 7, dan 5 record MY/DE lolos
auto-review menjadi published.

---

## 4. Angka

| Metrik | Sebelum fase ini | Sesudah |
|---|---:|---:|
| Approved | 134 | **139** |
| Punya deadline | 26 | **42** |
| Punya degree (tunggal/multi) | 106 | **106** |
| Punya funding type | 34 | **37** |
| Pending | 18 | 13 |

Per negara: GB 40, JP 37, DE 16, CN 16, ID 11, **MY 7**, SG 5, FR 2, BN 2, AU 1, KR 1, US 1.

Catatan: MY naik 3 → 7 karena provider identity dibetulkan, bukan karena crawl baru.

---

## 5. Test

```
1899 passed, 131 skipped, 0 failed
ruff check . → All checks passed
```

Test baru: `TestDeadlineAcrossLanguages` — 8 bentuk nyata (Melayu, Jerman,
Inggris) dan 2 kasus `DD/MM` ambigu yang harus **ditolak**, bukan ditebak.

---

## 6. Sisa & rekomendasi

1. **Deadline 42/139**: sisanya halaman tanpa tanggal. Untuk menembus 60 perlu
   record baru, bukan pola baru.
2. **Funding 37/139**: alias seperti "covers tuition fees, dormitory and
   stipend" sengaja tidak dipetakan karena menyebut sebagian komponen —
   memetakannya ke "Fully Funded" akan menjadi klaim yang tidak dibuat halaman.
3. **13 hold**: 7 provider masih batch label/domain tanpa bukti di halaman,
   5 nama masih judul halaman, 1 field wajib kurang.
4. **Langkah berikutnya paling berdampak**: Fase 3 (MY/BN depth) — halaman Melayu
   dan PDF pemerintah Brunei.
