# Precision Gate — Data Source & Name Quality

**Tanggal:** 10 November 2026
**Konteks:** lanjutan dari perbaikan funnel. Setelah discovery bisa menyimpan record, masalah berikutnya adalah *apa* yang disimpan.
**Status:** implemented + verified on fresh scratch databases.

---

## 1. Masalah yang diperbaiki

Live run pertama menyimpan record seperti:

- `JSPS Topics` — halaman berita/topik, bukan program.
- `2027-2028 Fellowship Categories` — daftar kategori, bukan satu fellowship.
- `Fees and funding`, `Guidelines on tuition fees`, `3. Interview` — bagian halaman.
- Record dari `wemakescholars.com`, `globaladmissions.com` — agregator, bukan sumber resmi.
- Nama dengan suffix publisher: `Tuition reduction system｜Study in Japan Official Website`.
- Provider dari domain: `Jpf`.

Semuanya lolos karena pipeline bertanya "apakah halaman ini menyebut beasiswa?" bukan "apakah halaman ini **satu** beasiswa, dari sumber resmi?".

---

## 2. Perubahan

### 2.1 Satu definisi "label section"

`services/domain/page_labels.py` — aturan struktural, bukan daftar string:

- heading bernomor (`3. Interview`, `1. Application Methods`) adalah langkah, bukan award;
- judul yang hanya kata section atau frasa pendek ber-head noun section (`Topics`, `Fellowship Categories`, `Guidelines on tuition fees`) adalah section;
- judul yang dimulai `About`/`Contact` dan lebih panjang dari nama adalah halaman organisasi;
- frasa proses/biaya (`fees and funding`, `tuition fees`, `how to apply`, `application process`, `academic year`) bukan nama program.

Dipakai oleh **page intent** dan **extraction quality**, sehingga keduanya tidak bisa berbeda pendapat.

### 2.2 Page intent

`services/exploration/page_intent.py`:

- rule 4c: label section → `SCHOLARSHIP_INDEX` (jika banyak link) atau `GENERAL_PROGRAMME_PAGE`; halaman `About us` tetap `PROVIDER_INFORMATION`;
- rule 4d: path koleksi (`/topics/`, `/categories/`, `/fees-and-funding/`, `/how-to-apply/`) tanpa detail language → index.

### 2.3 Nama: hard disqualifier

`services/ingestion/extraction_quality.py`:

- label section dan **policy generik** (`tuition reduction/exemption system` tanpa identitas) menjadi hard disqualifier, bukan sekadar penalti confidence;
- gate yang sama dipakai `assess_identity` di review, jadi record tidak bisa lolos publikasi dengan nama seperti itu;
- separator publisher full-width `｜` ikut dibersihkan;
- provider dari domain (`Jpf`, `jpf.go.jp`) ditolak; akronim nyata (`MIT`, `NUS`, `DAAD`, `JASSO`) tetap valid.

### 2.4 Sumber: agregator & platform sosial

`services/domain/source_trust.py` + gate terpusat di `FrontierRepository.upsert_candidate`:

- daftar agregator yang benar-benar muncul di katalog: wemakescholars, scholarshipbob, globalscholarships, scholarshipsads, globaladmissions, scholarshipshive, globalscholarshiphub, opportunitiesforyouth, prospects.ac.uk, dll.;
- platform sosial: YouTube, Facebook, Instagram, TikTok, X, LinkedIn, Reddit, WhatsApp, Telegram;
- gate ada di **admission frontier**, bukan hanya di search surface. Sebelumnya 32 URL globaladmissions masuk lewat link expansion;
- acquisition melewati sumber agregator (`SKIPPED`), verifier menolaknya (`REJECTED`), quality gate menandai `official_page_url` agregator sebagai `MISSING`.

---

## 3. Bukti

### 3.1 Golden dataset dari record nyata

`tests/golden/scholarship_name_labels.json` — 29 nama dari katalog development:

- **15 harus ditolak**: Topics, Categories, Fees, Guidelines, numbered headings, policy generik, statistik, About page.
- **14 harus diterima**: Dr Mai Yamani Scholarship, Humphrey Fellowship, MEXT, Chevening, Eiffel, DAAD, Fulbright, AUA scheme, MEXT Tuition Exemption, Fulbright Tuition Waiver, dll.

Dua lapis diuji:

- `name_genericities` — 29/29 sesuai label;
- `score_candidate_name(in_title=True, in_heading=True)` — 29/29 sesuai label; konteks halaman tidak bisa menyelamatkan nama section.

### 3.2 Live run

| Metrik | Sebelum gate | Sesudah gate |
|---|---:|---:|
| Record tersimpan | 2 | 1 |
| Record berupa section/policy generik | 2 | 0 |
| Host agregator/sosial di frontier | 32 | **0** |
| Lead agregator/sosial diblokir | 0 | **17** |
| Host teratas | campuran | studyinjapan, jsps, u-tokyo, jpf, jasso |

Record yang tersisa: `AUA Tuition Reduction/Exemption System` — skema spesifik milik satu universitas, masih `pending_review` dengan gate `degree`.

### 3.3 Test suite

- `ruff check .` bersih.
- **1802 passed, 137 skipped, 0 failed** di database bersih.

---

## 4. Ekspansi overview (implemented, belum terbukti di live)

`AcquisitionService._process_page` sekarang mengembalikan link program anak ketika halaman adalah `SCHOLARSHIP_OVERVIEW`/`INDEX`, dan antrean akuisisi memprosesnya satu level lebih dalam (maks 2 overview × 4 child per sumber). Child dipilih dari anchor yang menamai program, bukan dari URL policy, karena URL nyata seperti `/mext-scholarships/` tidak punya tahun atau nama tunggal.

Batasan yang ditemukan di live: halaman MEXT di studyinjapan tidak me-link ke tipe programnya (Research Students, dll.) sebagai anchor; daftar itu berupa teks/accordion. Jadi ekspansi tidak menemukan child di halaman itu. Fitur ini tetap benar dan teruji untuk overview yang memang berisi link program, tetapi **yield program bernama membutuhkan connector site-specific** untuk portal besar (studyinjapan search, JSPS, JASSO).

## 5. Yang belum selesai

- **Penemuan program bernama** masih tipis. Run 5 menit menemukan 1 skema spesifik; sebagian besar halaman resmi yang ditemukan adalah index/overview. Perlu ekspansi section satu level lebih dalam dan pemilihan link yang lebih baik.
- **Skema tuition reduction** yang spesifik tetap dianggap peluang pendanaan; reviewer memutuskan lewat `degree` dan kelengkapan.
- **Ekstraksi multilingual** belum setara.
- **Backlog review** 60 record lama belum dikosongkan.
- **Approval rate** belum diukur ulang pada katalog development; gate ini menurunkan input sampah, bukan menjamin reviewer menyetujui.

---

## 5. Kesimpulan

Polaris sekarang menolak halaman dan nama yang **bukan satu program**, dan tidak pernah mengantrekan agregator/platform sosial sebagai sumber resmi. Bottleneck berikutnya bukan "menemukan halaman", tetapi **menemukan halaman program yang bernama** dan **mengosongkan antrean review**.
