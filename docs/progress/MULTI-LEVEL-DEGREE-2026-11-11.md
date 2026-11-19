# Multi-Level Degree & Cross-Country Run — 11 November 2026

Lanjutan dari rilis 11 November. Fokus: menjalankan negara lain, menutup celah
struktural yang membuat mayoritas katalog Jepang tidak bisa dipublikasikan, dan
menaikkan katalog dari 58 → 84 record.

---

## 1. Hasil angka

| Metrik | Sebelum | Sesudah |
|---|---:|---:|
| Approved | 58 | **84** |
| Pending review | 33 | **37** |
| Rejected | 167 | 193 |
| Total record | 259 | 315 |
| Approval rate | 25,8% | 30,3% |

Per negara:

| Negara | Approved | Pending | Total |
|---|---:|---:|---:|
| GB | 33 | 20 | 88 |
| JP | **31** | 8 | 112 |
| ID | 6 | 6 | 26 |
| DE | 5 | 1 | 27 |
| SG | 5 | 1 | 56 |
| FR | 2 | 0 | 2 |
| US | 1 | 0 | 1 |
| AU | 1 | 0 | 1 |
| KR | 0 | 1 | 1 |
| CN | 0 | 0 | 1 |

Jepang naik dari 6 → 31 approved.

---

## 2. Temuan struktural: satu `degree` untuk program multi-level

Database resmi Jepang menyatakan level sebagai **himpunan**, bukan satu nilai:

```
Academic level:
- Doctoral degree program Master's degree program Bachelor's degree program
```

`scholarship.degree` hanya satu kolom. Extractor melihat lebih dari satu level,
menilainya "ambiguous", dan menyimpan NULL. Akibatnya:

- publication gate memblokir record (`degree` wajib);
- record tidak muncul di filter degree mana pun;
- matching memberi skor 0 pada kriteria degree (20 poin).

Ini bukan bug kecil: **16 dari 20 pending JP** terkena, dan itu populasi normal
database nasional — bukan kasus tepi.

### Yang dibangun

| Bagian | Perubahan |
|---|---|
| `services/domain/degree_levels.py` | Detektor deterministik: hanya blok berlabel (`Academic level`, `Available programs`, `Degree level`, `Level of study`) yang dihitung; satu level diserahkan ke jalur lama; daftar eligibilitas pelamar tidak dianggap level award |
| `database/models/scholarship_degree_level.py` + migrasi `c9e0f1a2b3d4` | Tabel anak, aditif; record satu-level tidak menulis baris apa pun |
| `services/ingestion/extractor.py`, `real_extractor.py` | Field `degree_levels` pada output extraction |
| `services/scholarship/mapper.py` | Menulis baris level saat halaman menyatakan himpunan |
| `services/review/quality.py` | Gate `degree` dianggap KNOWN bila level tersedia |
| `services/scholarship/repository.py` | Filter `degree=` mencakup kolom dan baris level |
| `services/matching/scoring/engine.py` | Skor degree cocok bila level profil ada di himpunan |
| `api/schemas.py`, `api/routers/scholarships.py` | `degree_levels` di list dan detail |
| `scripts/backfill_degree_levels.py` | Backfill dari `raw_document` yang sudah tersimpan, tanpa crawl ulang |
| `scripts/review_queue.py` | Perintah `correct` (`--set field=value`) memakai `ReviewService.correct` dengan audit |

Backfill: 48 dokumen dipindai, **16 record** mendapat level (43 baris). Spot-check
halaman Otsuka, Kang InSoo, Tama Art, Fukushima, Masajuro cocok dengan teks asli.

### Verifikasi

- `GET /api/v1/scholarships?degree=PhD` → 27 record, 10 di antaranya multi-level
  yang sebelumnya tidak mungkin muncul.
- Detail record menampilkan `degree_levels: ["Bachelor","Master","PhD"]`.

---

## 3. Negara lain

| Negara | Hasil | Catatan |
|---|---|---|
| FR | 2 approved (1 baru: MOPGA 2027) | Seed `campusfrance.org/en/eiffel-scholarship-program` 404 → diperbaiki ke URL yang benar |
| CN | 0 baru | Situs CSC/Campus China di belakang WAF (HTTP 412 untuk non-browser); `campuschina.org` tanpa `www` resolve, dengan `www` gagal DNS; seed config diperbaiki |
| AU | 0 baru | 5 ekstraksi, semuanya duplikat dari katalog yang ada |

Perbaikan runner yang diperlukan agar negara bisa jalan:

- `ensure_seed_sources()`: `seed_urls` dari config negara sekarang didaftarkan
  sebagai source. Sebelumnya config hanya dipakai exploration engine, sehingga
  negara dengan config valid tetap melaporkan 0 source.
- `--source-id` untuk crawl satu source (dipakai untuk work list importer).
- Provider code dipotong + hash bila > 32 karakter (`enseignementsup-recherche.gouv.fr`).

---

## 4. Perbaikan yang ikut terbawa

- **Work list importer diproses lebih dulu.** Sebelumnya URL hasil enumerasi
  database resmi ditambahkan di belakang link hasil discovery, sehingga budget
  halaman habis untuk link tebakan. Backfill JP: 57 halaman, 55 ekstraksi sukses,
  12 record baru, 43 duplikat.
- **Migrasi dev tertinggal.** Database dev masih memakai constraint `funding_type`
  lama (3 nilai) dan lifecycle lama; `alembic upgrade head` dijalankan, sekarang
  `c9e0f1a2b3d4`.
- **Test Phase 2 tidak hermetis** — seed config CN ikut aktif, jumlah provider
  jadi 9 bukan 3. Test sekarang menonaktifkan config lain dulu.

---

## 5. Review yang dilakukan

Keputusan dijalankan lewat `review_queue.py` dengan alasan tercatat, actor `owner`:

| Keputusan | Jumlah | Alasan |
|---|---:|---|
| Approve (batch awal, lintas negara) | 15 | Nama program jelas, degree ada, lolos semua gate |
| Approve JP multi-level | 11 | Program bernama + level dari halaman resmi |
| Reject JP | 25 | "Tuition reduction/exemption system" generik, pinjaman mahasiswa, atau nama tidak teridentifikasi |

Yang **ditahan** (bukan diputuskan): 4 record JP dengan nama ambigu
("Foreign Student Scholarship", "College of International Relations Scholarship",
"Financial Assistance Program for Foreign Students", "College of Science and
Technology Scholarship"). Provider-nya masih MEXT karena universitas belum
ter-resolve; mempublikasikannya akan menempelkan nama generik ke kementerian.

---

## 6. Status test

```
1855 passed, 131 skipped, 0 failed
ruff check . → All checks passed
```

Test baru: `tests/unit/test_degree_levels.py` (6 kasus: himpunan level,
satu baris, satu level, daftar eligibilitas, blok berhenti di label berikutnya,
tanpa label) dan 2 kasus gate di `test_review_quality.py`.

---

## 7. Yang masih terbuka

1. **37 pending**: 20 GB, 8 JP, 6 ID, 1 DE, 1 SG, 1 KR. Sebagian besar butuh
   identitas provider yang benar, bukan degree.
2. **Universitas belum ter-resolve** untuk halaman Study in Japan: provider
   jatuh ke MEXT. Perlu resolver nama universitas → entitas `University`.
3. **Level Kosen / College of Technology** di luar vocabulary degree
   (`Bachelor/Exchange/Master/PhD/Short Course`); 2 record JP menunggu keputusan
   apakah `Associate` ditambahkan.
4. **CN diblokir WAF**; perlu strategi berbeda (mis. mirror resmi atau API).
5. **Crawler belum dijalankan ulang dengan `degree_levels`** untuk negara lain;
   backfill hanya menyentuh record yang raw document-nya tersimpan.
