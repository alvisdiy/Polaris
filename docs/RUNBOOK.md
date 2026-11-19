# Polaris Runbook

Operasi harian Polaris tanpa AI di loop. Semua perintah di bawah deterministik:
input sama → keputusan sama, dan tidak ada langkah yang menunggu model.

---

## 1. Satu perintah untuk semuanya

```bash
python scripts/pipeline_run.py MY BN DE --max-total-pages 120 --runtime 14
python scripts/pipeline_run.py --all --skip-recent-days 7
```

Urutan per negara:

```
seeds → discover (opsional) → crawl → enrich → auto-review
```

| Langkah | Perintah terpisah (kalau perlu debug) |
|---|---|
| seeds | `python scripts/run_country_crawl.py MY --plan-only` |
| discover | `python scripts/run_country_crawl.py MY --discover` |
| crawl | `python scripts/run_country_crawl.py MY --max-total-pages 120` |
| enrich | `python scripts/enrich_records.py --state all` |
| auto-review | `python scripts/auto_review.py` |

Run record: `.zwork/pipeline_runs/<timestamp>.json`.

---

## 2. Menambah negara baru

Cukup tambah satu file, tidak ada perubahan kode:

`configs/countries/XX.json`

```json
{
  "iso2": "MY",
  "iso3": "MYS",
  "country_name": "Malaysia",
  "country_local": "Malaysia",
  "languages": ["en", "ms"],
  "search_locale": "en-MY",
  "search_gl": "my",
  "terminology": { "scholarship": ["scholarship", "biasiswa"], "...": [] },
  "soft_domain_signals": [".edu.my", ".gov.my"],
  "seed_urls": ["https://biasiswa.mohe.gov.my/biasiswa/"],
  "max_queries_per_run": 12
}
```

Aturan seed yang penting:

1. **Harus halaman resmi penyelenggara**, bukan agregator/blog.
2. **Harus hidup** — cek dulu `curl -o NUL -s -w "%{http_code}" <url>`; seed mati
   membuat run melaporkan nol dengan alasan yang menyesatkan (kasus CN).
3. Kalau portal nasional diblokir WAF, pakai situs universitas: beasiswa
   nasionalnya tetap resmi diterbitkan di sana.

Negara otomatis didaftarkan ke tabel `country` pada run pertama (dari `iso3`).

---

## 3. Menjadwalkan

Linux/macOS:

```cron
0 3 * * * cd /path/to/polaris && .venv/bin/python scripts/pipeline_run.py --all --skip-recent-days 7 >> .zwork/nightly.log 2>&1
```

Windows:

```powershell
schtasks /create /tn "Polaris nightly" /sc daily /st 03:00 /tr ^
 "C:\data\AINGMAUNGG\Polaris\.venv\Scripts\python.exe C:\data\AINGMAUNGG\Polaris\scripts\pipeline_run.py --all --skip-recent-days 7"
```

Exit code: `0` sukses, `1` ada negara error, `2` argumen salah.

Menjalankan dua kali berturut-turut aman: crawl melewati halaman yang baru
diambil (`--skip-recent-days`), enrichment tidak menimpa nilai yang ada, dan
auto-review memberi keputusan yang sama.

---

## 4. Apa yang diputuskan mesin, dan apa yang tidak

`scripts/auto_review.py` hanya punya tiga keluaran:

| Keputusan | Syarat |
|---|---|
| `approve` | lolos **semua** publication gate, nama mengidentifikasi program, sumber resmi |
| `reject` | tidak mungkin layak: duplikat, agregator/job board, kantor/berita, kebijakan biaya generik, siklus ditutup, nama fixture |
| `hold` | field wajib kurang, provider masih hostname/batch label, nama masih judul halaman |

Tidak ada override gate di jalur ini. Keputusan tercatat di audit trail dengan
actor `auto-review`.

Melihat antrean hold:

```bash
python scripts/review_queue.py list --limit 20
```

Menyelesaikan satu hold (contoh: provider masih hostname):

```bash
python scripts/review_queue.py --actor owner correct <id> \
  --set scholarship_name="Sun Yat-sen University Scholarship for International Students" \
  --reason "page names the university scholarship" --evidence-url <url> --yes
```

---

## 5. Kalau ada yang aneh

| Gejala | Periksa |
|---|---|
| negara melaporkan 0 source | `configs/countries/XX.json` seed hidup? provider terdaftar? |
| crawl jalan tapi 0 record | halaman bukan program (overview/policy), atau gate presisi menolak — lihat `quality_report` |
| banyak hold `provider_identity` | nama provider masih domain/batch label; perbaiki lewat `correct --set provider_id` |
| record hilang dari API | `deadline_state = expired` (perilaku benar) atau status belum `approved` |
| pipeline exit 1 | baca `.zwork/pipeline_runs/<ts>.json` bagian `errors` |

---

## 6. Batas yang tidak boleh dilanggar

- Live crawl hanya ke database `*_test` / `*_scratch`; `--allow-non-scratch` hanya
  untuk dev yang memang disengaja.
- Agregator, sosial, blog, job board tidak pernah jadi sumber resmi.
- Tidak ada auto-approve yang meng-override gate. `approve` hanya untuk record
  yang lolos.
- Deadline tidak pernah dikarang; kalau halaman tidak menyebut, nilainya kosong.
