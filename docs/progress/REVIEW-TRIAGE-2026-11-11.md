# Review Triage — 11 November 2026

**Sumber:** 60 record `pending_review` di database development.
**File keputusan:** `artifacts/review_triage_2026-11-11.csv` (semua 60 record + proposed action).
**Sifat:** rekomendasi. Tidak ada record yang diubah saat triage ini dibuat.

---

## 1. Ringkasan

| Proposed action | Jumlah | Arti |
|---|---:|---|
| `complete: degree,funding,deadline` | 26 | Program asli, tiga field inti kosong |
| `complete: funding,deadline` | 13 | Degree ada, funding & deadline kosong |
| `complete: degree,deadline` | 3 | Funding ada, degree & deadline kosong |
| `complete: degree,funding` | 3 | Deadline ada, degree & funding kosong |
| `complete: deadline` | 3 | Hanya deadline kosong |
| `reject: name` | 6 | Nama section/policy, bukan program |
| `review: job board` | 3 | jobs.ac.uk, bukan sumber resmi |
| `review: not a programme` | 2 | Halaman berita/komentar |
| `approve candidate` | 1 | Field lengkap |

**Kesimpulan:** 48 dari 60 adalah program nyata yang **belum lengkap**, bukan sampah. Bottleneck-nya adalah completion + keputusan, bukan penambahan supply.

---

## 2. Buang dulu yang jelas bukan program (11)

### 2.1 Nama section/policy (6)

| ID | Nama | Alasan |
|---|---|---|
| `f8849717` | International student tuition reduction and exemption system | policy generik |
| `8574bd48` | JSPS Topics | halaman topik |
| `afc33577` | Value and Length of Funding | section |
| `cb9cfd7e` | Tuition fees for research courses 2026-2027 | halaman biaya |
| `9f24fcd8` | Tuition fees for taught courses 2026-2027 | halaman biaya |
| `baa6ed56` | Tuition fees for taught courses 2027-2028 | halaman biaya |

```bash
python scripts/review_queue.py reject <id> --actor <you> \
  --reason "section label, not a programme" --yes
```

### 2.2 Job board (3)

`jobs.ac.uk` adalah papan lowongan, bukan provider resmi. Tiga record PhD studentship masuk dari sana:

- `13200cd2` PhD Studentship in Medicinal Chemistry…
- `2f1d5368` PhD Studentship: Investigating Molecular Drivers…
- `53555526` School of Natural Sciences PhD studentship…

Rekomendasi: reject dengan alasan `job board, not an official provider`. Kalau nanti Polaris memang mau mencakup PhD studentship, sumber resminya adalah halaman universitas, bukan jobs.ac.uk.

### 2.3 Halaman berita/komentar (2)

- `76c98c65` Chevening scholars | International students (sheffield.ac.uk)
- `a6f9dee6` 2026 Comments by Selection Committee Chair (toyotafound.or.jp)

Rekomendasi: reject dengan alasan `news/commentary page, not one programme`.

---

## 3. Kandidat approve (1)

`8d1ed5d0` **AHRC Landscape Award Studentships** (bbk.ac.uk) — degree, funding, dan deadline terisi. Periksa halaman resminya sekali, lalu:

```bash
python scripts/review_queue.py approve 8d1ed5d0... --actor <you> \
  --reason "complete record, verified against the official page" --yes
```

Jangan approve hanya karena gate lolos; baca halamannya.

---

## 4. Lengkapi 48 record (pekerjaan utama)

Urutan yang disarankan:

1. **13 record** yang hanya kurang funding+deadline — paling cepat menambah nilai katalog.
2. **26 record** yang kurang degree+funding+deadline — butuh verifikasi halaman lebih dalam.
3. Sisanya (9 record) kurang satu atau dua field.

Cara yang benar: **candidate revision**, bukan update langsung.

```text
ReviewService.propose_candidate(scholarship_id, changes, source_url, actor)
  → reviewer melihat diff + evidence
  → ReviewService.approve_candidate(candidate_id, actor, reason)
```

Ini menjaga version row + audit action tetap ditulis, dan record approved tidak pernah ditimpa diam-diam.

Yang perlu dibangun berikutnya: `scripts/complete_record.py` — fetch halaman resmi, jalankan extractor, tampilkan field yang ditemukan vs yang kosong, lalu buat candidate revision. Itu alat, bukan keputusan; reviewer tetap yang approve.

---

## 5. Definisi selesai

- Backlog `pending_review` < 7 hari.
- 11 record invalid diputuskan (reject).
- 48 record dilengkapi atau ditolak dengan alasan.
- Approval rate record baru diukur setelah gate presisi (target ≥ 50%).
- Completeness katalog: deadline ≥ 80%, funding ≥ 70%, degree ≥ 90%.

---

## 6. Yang jangan dilakukan sekarang

- Menambah connector/supply sebelum antrean 60 selesai. Supply baru hanya menambah backlog.
- Approve massal tanpa membaca halaman; degree/funding/deadline adalah bahan matching, bukan formalitas.
- Menurunkan quality gate agar angka approval naik.

---

## 7. Eksekusi 11 November 2026

Setelah triage disetujui, 11 record diputuskan lewat `scripts/review_queue.py` dengan actor `owner`:

- **10 rejected**: 5 halaman section/policy, 3 job board (`jobs.ac.uk`), 2 halaman berita/komentar.
- **1 approved**: `AHRC Landscape Award Studentships` (bbk.ac.uk) — punya degree, funding, deadline, dan version row.
- **1 ditunda**: `Value and Length of Funding` (bbk.ac.uk) ternyata halaman studentship asli; namanya salah ambil heading. Record tetap `pending_review` untuk pass completion, bukan di-reject.

Hasil antrean:

| Metrik | Sebelum | Sesudah |
|---|---:|---:|
| Pending review | 60 | **49** |
| Approved | 41 | **42** |
| Rejected | 157 | **167** |
| Approval rate | 20,7% | 20,1% |

Temuan engineering: CLI versi pertama hanya `flush` tanpa `commit`, sehingga keputusan tidak tersimpan saat proses keluar. Sudah diperbaiki (`session.commit()` untuk approve/reject, `rollback()` saat refused) dan test suite tetap hijau. Ini juga alasan audit trail diperiksa setelah eksekusi, bukan hanya output CLI.

