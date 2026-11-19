# Autonomous Pipeline & Review — 12 November 2026

Tujuan yang diminta: pipeline pencarian beasiswa harus jalan **sendiri**, dan
hasil crawl harus bisa direview **tanpa AI**, karena setiap audit manual yang
dibantu model menguras token.

Hasilnya: satu perintah menjalankan seluruh siklus, dan review-nya deterministik.
Pada uji pertama, **43 pending → 29 published, 7 rejected, 7 held** tanpa satu
pun keputusan model.

---

## 1. Satu perintah untuk semuanya

```bash
python scripts/pipeline_run.py MY BN DE --max-total-pages 120 --runtime 14
python scripts/pipeline_run.py --all --skip-recent-days 7
python scripts/pipeline_run.py MY --plan-only      # buka DB? tidak
```

Tiap negara menjalani lima langkah, semuanya terbatas dan idempoten:

| Langkah | Yang dikerjakan | Bisa diulang? |
|---|---|---|
| seeds | `seed_urls` config didaftarkan sebagai source | ya — tidak menduplikasi |
| discover | provider discovery dari surface resmi (opsional, `--discover`) | ya — digabung per domain |
| crawl | halaman program dalam budget | ya — `--skip-recent-days` |
| enrich | field kosong diisi dari dokumen tersimpan | ya — nilai yang ada tidak ditimpa |
| auto-review | approve/reject/hold menurut gate | ya — keputusan sama tiap run |

Run record ditulis ke `.zwork/pipeline_runs/<timestamp>.json`, jadi bisa diaudit
tanpa membaca log.

Penjadwalan (tidak perlu AI, tidak perlu orang):

```cron
# cron
0 3 * * * cd /path/to/polaris && .venv/bin/python scripts/pipeline_run.py --all --skip-recent-days 7
```

```powershell
# Windows Task Scheduler
schtasks /create /tn "Polaris nightly" /sc daily /st 03:00 ^
  /tr "C:\data\AINGMAUNGG\Polaris\.venv\Scripts\python.exe C:\data\AINGMAUNGG\Polaris\scripts\pipeline_run.py --all --skip-recent-days 7"
```

Exit code: `0` sukses, `1` ada negara gagal, `2` argumen salah — jadi scheduler
bisa membedakan "jalan tapi kosong" dari "rusak".

---

## 2. Review tanpa AI

`scripts/auto_review.py` memutuskan tiap record pending dengan aturan, bukan
penilaian:

| Keputusan | Syarat | Contoh |
|---|---|---|
| **approve** | lolos semua publication gate, nama mengidentifikasi program, sumber resmi | SOAS Grant 2026/27 |
| **reject** | tidak mungkin jadi layak: duplikat, halaman agregator, kantor/berita, kebijakan biaya generik, siklus ditutup | "Government Grants Managed Service (GGMS)", "Modernising grant administration" |
| **hold** | ambigu: field wajib kurang, provider masih hostname, nama masih judul halaman | "sysu.edu.cn", "… 2022.5.12掲載 - 筑波大学" |

Tidak ada override gate di jalur ini. "Approve" berarti **gate-nya lolos**, bukan
"menurut saya bagus". Setiap keputusan tercatat di audit trail dengan actor
`auto-review` dan alasannya.

Yang penting: **hold bukan kegagalan**. Antrean 43 record jadi 7 hold — dan 7 itu
memang butuh keputusan yang tidak bisa ditebak mesin (nama program, identitas
penyelenggara).

---

## 3. Yang diubah supaya tidak terlalu ketat

### 3.1 `degree` jadi soft field

Ini penyebab 36 dari 43 record nyangkut. Banyak halaman menjelaskan **siapa yang
boleh melamar** tanpa menyebut **level award**-nya. Menolak record seperti itu
membuang beasiswa nyata dari katalog.

Sekarang:

- `degree` **tidak lagi** ada di `REQUIRED_TO_PUBLISH`;
- nilainya tetap dilaporkan `UNKNOWN` dengan alasan "level not stated on the page";
- konflik level tetap memblokir, dan nilai tetap divalidasi terhadap vocabulary.

### 3.2 Matching tidak menghukum data yang tidak ada

Skor degree dulu 0 kalau level kosong, sehingga beasiswa yang tidak menyebut level
selalu kalah dari yang menyebut — bukan karena kurang cocok, tapi karena kurang
terdokumentasi. Sekarang:

- level kosong → kriteria dinilai **netral** (tidak dihukum), dengan alasan tertulis;
- level ada dan tidak cocok → tetap 0.

### 3.3 Inference deterministik, bukan tebakan

`services/domain/degree_fallback.py` mengisi level hanya kalau buktinya tunggal:

| Sinyal | Hasil |
|---|---|
| nama memuat "PhD"/"Doctoral" | PhD |
| nama memuat "Master's"/"MBA"/"MSc" | Master |
| nama memuat "Bachelor's"/"Undergraduate" | Bachelor |
| nama memuat "Erasmus"/"Exchange" | Exchange |
| URL di bawah `/masters-funding/`, `/phd/`, `/undergraduate/` | sesuai segmen |
| dua sinyal berbeda, atau hanya "postgraduate" | **tetap kosong** |

"Postgraduate" sengaja tidak dipetakan: di Inggris itu mencakup Master **dan**
PhD. Menebaknya akan menaruh nilai salah pada separuh record.

### 3.4 Enrichment mengisi field kosong dari dokumen tersimpan

`scripts/enrich_records.py` membaca ulang `raw_document` lalu mengisi deadline,
funding, degree, field of study, GPA, TOEFL — hanya bila extractor memberi **satu**
jawaban, deadline tidak kontradiktif, dan tanggalnya masuk akal. Semua lewat
`ReviewService.correct()` dengan actor `enrichment`, jadi ada versi + audit.

Uji pada 43 pending: 8 degree + 1 deadline terisi. Sisanya memang tidak
menyebutkannya di halaman.

---

## 4. Bug yang ketemu saat membangun ini

| Bug | Dampak | Perbaikan |
|---|---|---|
| `application_deadline` memblokir tapi tidak ada di daftar `overridable_fields` | reviewer tidak bisa override field yang seharusnya bisa | kedua ejaan dimasukkan |
| `\b` setelah tanggal gagal di nama CJK | nama "…2022.5.12掲載" lolos pemeriksaan kebersihan nama | lookahead `(?![0-9])` |
| Halaman administrasi/berita lolos gate | "Government Grants Managed Service" akan terbit sebagai beasiswa | daftar pola `NOT_A_PROGRAMME` + provider direktori |

---

## 5. Angka

| Metrik | Sebelum sesi ini | Sesudah |
|---|---:|---:|
| Pending review | 43 | **7** |
| Approved | 91 | **120** |
| Rejected | 205 | 212 |
| Total | 340 | 340 |

Semua 29 approval baru berasal dari aturan deterministik, bukan dari review manual.

Test: `1884 passed, 131 skipped` setelah perubahan ini (lihat laporan berikutnya
untuk angka final bila pipeline menambah data).

---

## 6. Yang masih perlu manusia (dan itu wajar)

1. **7 hold**: 4 provider masih hostname/batch label, 2 nama masih judul halaman,
   1 kurang field wajib. Semua punya alasan tertulis di antrean.
2. **Deadline lengkap**: hanya sebagian halaman yang mencantumkan tanggal. Pipeline
   tidak akan mengarang.
3. **Provider identity** untuk record yang penyelenggaranya yayasan/perusahaan
   (Otsuka Toshimi, INPEX, JEES) — bukan universitas, jadi tidak bisa ditebak dari
   domain kampus.
