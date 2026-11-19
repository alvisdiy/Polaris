# Data Expansion & Autonomy Run — 12 November 2026

Dua hal yang diminta: katalog diperkaya dari negara lain, dan pipeline-nya bisa
jalan sendiri tanpa AI. Keduanya selesai; laporan ini mencatat angka dan batasnya.

---

## 1. Katalog

| Metrik | Sebelum | Sesudah |
|---|---:|---:|
| Approved | 91 | **134** |
| Pending | 43 | **18** |
| Rejected | 205 | 213 |
| Total | 340 | 366 |
| Katalog publik (API) | 89 | **130** |

Per negara (publik): GB 40, JP 37, CN 14, **DE 14**, ID 11, SG 5, **MY 3**,
**BN 2**, FR 2, AU 1, US 1.

Negara baru:

- **Malaysia** — 8 seed portal (biasiswa.mohe.gov.my, mohe.gov.my, MARA, UM, USM,
  UKM, UPM, UTM) + 14 halaman beasiswa dari discovery `site:edu.my`.
- **Brunei** — 4 seed portal (moe.gov.bn, mof.gov.bn, UBD, UTB) + 9 halaman dari
  discovery `site:edu.bn`.
- **Jerman** — seed ditambah Deutschlandstipendium, DFG, TUM; hasil naik dari 5
  ke 14 approved.

Contoh record baru: *ASEAN SHIELD Cyber Security Scholarship* (UTB), *MoHE Higher
Education Funding* (Malaysia), *Deutschlandstipendium*-derived awards.

---

## 2. Pipeline yang jalan sendiri

Satu perintah, lima langkah, tanpa AI:

```bash
python scripts/pipeline_run.py MY BN DE --max-total-pages 120 --runtime 14
```

`seeds → discover → crawl → enrich → auto-review`, dengan run record JSON di
`.zwork/pipeline_runs/`. Detail operasional: [docs/RUNBOOK.md](../RUNBOOK.md).

---

## 3. Review deterministik: hasil nyata

`scripts/auto_review.py` mengubah 43 pending menjadi:

| Keputusan | Jumlah | Contoh |
|---|---:|---|
| approve | 29 | SOAS Grant, Fulbright US–ASEAN, Sanctuary Scholarship, GKS Undergraduate |
| reject | 7 | halaman berita/administrasi, kebijakan biaya generik, duplikat |
| hold | 7 | provider masih hostname, nama masih judul halaman |

Artinya: **29 beasiswa masuk katalog tanpa satu pun keputusan model.**

Aturan yang dipakai (semua deterministik):

- approve hanya bila lolos semua publication gate, nama mengidentifikasi program,
  dan sumber resmi;
- reject bila tidak mungkin layak (agregator/job board, kantor/berita, kebijakan
  biaya generik, siklus ditutup, nama fixture);
- hold untuk yang ambigu, dengan alasan tertulis.

---

## 4. Yang dilonggarkan (dan kenapa)

### 4.1 `degree` jadi soft field

36 dari 43 pending tertahan hanya karena level tidak disebut. Banyak halaman
menjelaskan siapa yang boleh melamar tanpa menyebut level award — menolak mereka
membuang beasiswa nyata. Sekarang level kosong **dilaporkan**, bukan diblokir.

### 4.2 Matching tidak menghukum data kosong

Skor degree dulu 0 saat level kosong, jadi beasiswa tanpa level selalu kalah —
bukan karena tidak cocok, tapi karena kurang terdokumentasi. Sekarang netral.

### 4.3 Inference deterministik

`services/domain/degree_fallback.py` mengisi level hanya bila bukti tunggal: nama
("PhD", "Master's", "Bachelor's", "Erasmus") atau segmen URL (`/masters-funding/`,
`/phd/`, `/undergraduate/`). Dua sinyal berbeda → tetap kosong. "Postgraduate"
tidak dipetakan karena mencakup Master dan PhD.

### 4.4 Tidak ada auto-approve yang meng-override gate

`approve` berarti "gate lolos". Tidak ada jalur yang menerbitkan record dengan
field wajib hilang.

---

## 5. Bug yang ketemu

| Bug | Dampak | Perbaikan |
|---|---|---|
| `CrawlTotals` dibaca dengan nama field yang salah | pipeline melaporkan error padahal crawl sukses | nama field disamakan |
| Negara baru tidak ada di tabel `country` | `Country not found: MY` | pipeline mendaftarkan negara dari `iso3` di config |
| `application_deadline` tidak ada di daftar override | reviewer tidak bisa override field yang seharusnya bisa | kedua ejaan dimasukkan |
| Nama fixture lolos gate | "MEXT Scholarship (Test)" terbit | aturan `test_record` + record ditarik |
| `\b` setelah tanggal gagal pada nama CJK | nama "…2022.5.12掲載" lolos | lookahead |

---

## 6. Batas yang masih ada

1. **18 pending**: 6 MY (judul halaman: "UTAMA", "Sustainability@UM"), 6 CN,
   5 DE, 1 JP. Semua punya alasan hold yang bisa dibaca.
2. **Malaysia yield rendah**: portal MoHE memakai JavaScript dan banyak halaman
   berbahasa Melayu; extractor menghasilkan judul halaman, bukan nama program.
   Perbaikan berikutnya: penanganan halaman berbahasa Melayu + selektor listing.
3. **Brunei baru 2**: domain `.edu.bn` sedikit; scholarship pemerintah
   (mofe/mindef) masih berupa PDF.
4. **Deadline hanya 26/130**: mayoritas halaman memang tidak mencantumkan tanggal.
   Pipeline tidak akan mengarang.
5. **Provider identity**: record yayasan/perusahaan (Otsuka Toshimi, INPEX, JEES)
   tetap bukan universitas — menebaknya akan salah.

---

## 7. Test

```
1889 passed, 131 skipped, 0 failed
ruff check . → All checks passed
```

Test baru: `tests/unit/test_auto_review.py` (14 kasus keputusan) dan
`tests/unit/test_degree_fallback.py` (8 kasus inference).
