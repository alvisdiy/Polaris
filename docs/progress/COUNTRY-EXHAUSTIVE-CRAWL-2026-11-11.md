# Per-Country Exhaustive Crawl — 11 November 2026

**Tujuan:** menjawab "run per country harusnya nyari semua beasiswa yang mungkin di negara itu".
**Status:** mekanisme selesai dan terbukti pada database resmi terbesar Jepang.

---

## 1. Definisi "semua yang mungkin"

Tidak ada crawler yang bisa menjamin seluruh beasiswa di dunia. Yang bisa dijamin:

1. semua **provider resmi** yang terdaftar untuk negara itu,
2. semua **halaman beasiswa** yang bisa dijangkau dari provider tersebut dalam batas kedalaman yang ditentukan,
3. semua **record** yang lolos precision gate, masuk `pending_review`.

Batasnya eksplisit: sumber, halaman per sumber, total halaman, runtime. Di luar batas itu bukan "gagal", tetapi "belum dijadwalkan".

---

## 2. Yang dibangun

### 2.1 `run_country_crawl.py`

Runner per-country yang menghabiskan **semua sumber aktif**:

```bash
python scripts/run_country_crawl.py JP --plan-only
python scripts/run_country_crawl.py JP --discover --max-total-pages 300
python scripts/run_country_crawl.py JP --skip-recent-days 1 --max-sources 4 \
  --max-pages-per-source 50 --max-total-pages 200
```

- `--discover`: jalankan provider/source discovery dulu (government/agency/university).
- traversal: homepage provider → section "Scholarships" → halaman program → ekstraksi.
- kedalaman index 2, maks 50 ekspansi index per sumber, 10 child per index.
- budget total halaman + runtime; berhenti rapi, bukan crash.
- `--skip-recent-days` untuk melanjutkan batch tanpa mengulang sumber yang baru diproses.
- guard database `_test`/`_scratch`; `--plan-only` tidak membuka DB.

### 2.2 `AcquisitionService` menerima work list

`source.scholarship_page_urls` sekarang dibaca sebagai daftar halaman yang harus diproses, bukan hanya ditulis. Ini memungkinkan satu source menampung ratusan detail dari database resmi, sementara discovery tetap berjalan untuk halaman lain.

- `source_seed` ditandai di `scholarship_page_urls`;
- dedup canonical terhadap entry page dan halaman yang sudah ada;
- batas 1.000 URL per source.

### 2.3 Importer database Study in Japan

`scripts/import_studyinjapan.py`:

- database resmi Study in Japan memaginasi 25 detail per halaman lewat JavaScript `page(offset)`;
- HTTP langsung dengan parameter yang sama mengembalikan halaman 1, karena server membutuhkan sesi — Playwright mempertahankan sesi itu;
- enumerator berhenti sendiri saat halaman terakhir hanya berisi 11 hasil;
- 661 detail URL ditemukan dari 30 halaman;
- URL dipecah menjadi batch 50 dan disimpan sebagai SourceRegistry `priority=0` (source lama tanpa batch di-retire);
- idempotent: batch yang sama di-update, bukan diduplikasi.

```bash
python scripts/import_studyinjapan.py --max-pages 30            # dry run
python scripts/import_studyinjapan.py --max-pages 30 --register # 14 batch
```

---

## 3. Bukti

### 3.1 Enumerasi

| Ukuran | Nilai |
|---|---:|
| Halaman pencarian diproses | 30 |
| Detail URL ditemukan | **661** |
| Halaman terakhir | 11 hasil (< 25, berhenti) |
| Batch dibuat | 14 (50 URL; batch 14 = 11) |

### 3.2 Crawl seluruh database

| Batch | Halaman | Ekstraksi sukses | Record baru | Duplikat |
|---|---:|---:|---:|---:|
| 1–4 | 200 | 33 | 7 | 26 |
| 5–8 | 200 | 43 | 21 | 22 |
| 9–12 | 200 | 31 | 13 | 18 |
| 13–14 | 93 | 14 | 5 | 9 |
| **Total** | **693** | **121** | **46** | **75** |

Katalog akhir di scratch: **59 record `pending_review`**, **55** di antaranya berasal dari database Study in Japan. Contoh nama: `Aichi Scholarship Program`, `INPEX Scholarship`, `JEES・Johnson Controls Scholarship`, `Hamamatsu University School of Medicine International Exchange Scholarship`, `Gakushuin University Tuition Reduction Program`.

Tidak ada record yang di-approve otomatis; semuanya menunggu review.

### 3.3 Test

- `ruff check .` bersih.
- **1841 passed, 137 skipped, 0 failed**.

---

## 4. Yang belum

1. **Baru satu database.** JASSO, JSPS, dan database universitas belum punya importer sendiri. Mekanisme batch + `scholarship_page_urls` sudah siap; tinggal connector per portal.
2. **Ekstraksi 121/693 (~17%).** 166 halaman gagal ekstraksi; sebagian besar halaman tuition-reduction/policy atau overview yang ditolak precision gate. Ini perlu triage, bukan pelonggaran gate.
3. **59 record belum direview.** Gunakan `scripts/review_queue.py`; approval rate belum diukur.
4. **Negara lain belum dijalankan dengan mode ini.** Provider discovery government/agency sudah ada; tinggal `run_country_crawl.py` per negara.
5. **Beasiswa dari universitas** masih bergantung pada provider discovery; directory universitas resmi (bukan Wikipedia) belum lengkap.

---

## 5. Urutan berikutnya

1. Review 59 record → ukur approval rate.
2. Tambah importer JASSO/JSPS (pola yang sama: enumerasi database resmi → batch).
3. Jalankan `run_country_crawl.py` untuk FR/CN/AU/GB dengan `--discover`.
4. Triage 166 extraction failures untuk memisahkan "bukan program" dari "gate terlalu ketat".
