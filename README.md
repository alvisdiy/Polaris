# Polaris

Platform intelijen beasiswa: menemukan beasiswa dari **sumber resmi**, mengekstrak faktanya, menyimpannya lewat jalur review, lalu mencocokkannya dengan profil mahasiswa secara deterministik.

Polaris bukan sekadar katalog. Ada rantai yang harus utuh dari halaman resmi sampai rekomendasi:

```text
source resmi → discovery → acquisition → ekstraksi deterministik → validasi
→ dedup identitas → review manusia → API publik → matching → frontend
```

Aturan yang tidak boleh dilanggar:

- **Sumber resmi dulu.** Blog, forum, dan portal agregator bukan sumber otoritatif.
- **LLM bukan sumber kebenaran.** Ekstraksi berjalan dengan aturan deterministik; tidak ada teks halaman yang bisa mengubah status publikasi.
- **Hanya `extraction_status = approved` yang terlihat publik.** Review adalah batas publikasi, bukan formalitas.

---

## Status

Status terkini yang terverifikasi ada di [STATUS.md](STATUS.md) — itu satu-satunya dokumen status yang hidup. Angka katalog di dokumen lama adalah snapshot pada tanggalnya masing-masing.

- Funnel discovery → review sudah berjalan end-to-end. Live run JP menghasilkan record nyata di `pending_review`.
- Test suite berjalan di database bersih. Test yang membutuhkan knowledge base development ditandai `data` dan di-skip secara default.
- Frontend: Vue 3 + Vite, build dan typecheck lulus.

Dokumen rekomendasi terbaru: [docs/progress/AS-IS-RECOMMENDATION-2026-11-09.md](docs/progress/AS-IS-RECOMMENDATION-2026-11-09.md).

---

## Arsitektur singkat

| Lapisan | Lokasi | Isi |
|---|---|---|
| API | `api/` | FastAPI, router publik + admin review, penyajian SPA |
| Matching | `services/matching/` | Filter deadline → scoring berbobot → ranking → explanation |
| Katalog | `services/scholarship/` | Repository, mapper, identity/dedup, freshness |
| Review | `services/review/` | State machine publikasi, audit trail, candidate revision |
| Ingestion | `services/ingestion/` | Connector, cleaner, extractor, validator, safety layer |
| Exploration | `services/exploration/` | Query generation, search provider, frontier, page intent, acquisition |
| Agregator | `services/aggregator_discovery/` | Adapter feed/HTML + verifikasi halaman resmi |
| Database | `database/` | SQLAlchemy models + migrasi Alembic |
| Frontend | `frontend/` | Vue 3 SPA (discover, detail, match, compare, saved) |

Spesifikasi dan keputusan desain ada di [IDEA.md](IDEA.md) dan [docs/v0.1/](docs/v0.1/).

---

## Quickstart dengan Docker

Prasyarat: Docker + Docker Compose.

```bash
# Token admin wajib. Tanpa ini, surface review sengaja dimatikan (503).
export POLARIS_ADMIN_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")

docker compose up --build
```

- API: <http://localhost:8000>
- Dokumentasi OpenAPI: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

Container menjalankan `alembic upgrade head` sebelum start. Database Postgres disimpan di volume `polaris-db`.

Untuk menjalankan discovery di dalam image:

```bash
docker compose run --rm api python scripts/run_country_exploration.py JP --plan-only
```

---

## Quickstart lokal

Prasyarat: Python 3.11+, Node.js 20+, PostgreSQL 16.

```bash
# 1. Backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux/macOS
pip install -e ".[dev]"

# 2. Konfigurasi
copy .env.example .env            # Windows
# cp .env.example .env            # Linux/macOS
# Isi DATABASE_URL dan POLARIS_ADMIN_TOKEN di .env

# 3. Skema + reference data
alembic upgrade head
python scripts/seed_source_registry.py
python scripts/seed_provider_discovery_config.py

# 4. Jalankan API
uvicorn api.app:app --reload --port 8000
```

```bash
# 5. Frontend (terminal terpisah)
cd frontend
npm ci
npm run dev        # http://localhost:3000, proxy /api/v1 → :8000
```

Atau dari root repo, satu perintah untuk API dan frontend sekaligus (API
ditunggu sampai `/health` hijau sebelum Vite dinyalakan, dan keduanya berhenti
bersama):

```bash
npm run dev        # API :8000 + frontend :3000
```

Build produksi frontend:

```bash
cd frontend
npm run build      # menghasilkan frontend/dist, dilayani API sebagai SPA
```

---

## Environment variables

| Variable | Wajib | Keterangan |
|---|---:|---|
| `DATABASE_URL` | ya | `postgresql+psycopg://user:pass@host:5432/db` |
| `POLARIS_ADMIN_TOKEN` | ya untuk review | Bearer token `/api/v1/admin/review/*`. Unset = 503 |
| `POLARIS_SEARCH_PROVIDER` | tidak | `ddgs` (default), `serper`, `null` |
| `POLARIS_SERPER_API_KEY` | hanya `serper` | Kredensial Serper.dev |
| `DDGS_PROXY` | tidak | Proxy opsional untuk DDGS |
| `POLARIS_ALLOWED_ORIGINS` | tidak | Origin CORS, dipisah koma. Kosong = single-origin |
| `POLARIS_ALLOW_NON_SCRATCH` | tidak | `1` = izinkan live run ke DB non-scratch (hati-hati) |
| `PORT` | tidak | Port API di container (default 8000) |

---

## Frontend

Vue 3 + Vite, arah visual "research ledger": kertas hangat, Fraunces/Instrument
Sans/IBM Plex Mono, satu aksen vermilion, dan globe wireframe SVG di hero
(dekoratif, tanpa dependency dan tanpa animasi). Sistem desain lengkap:
[docs/design/DESIGN.md](docs/design/DESIGN.md).

```bash
npm run dev                                   # dari root: API + frontend
cd frontend && npm install && npm run dev     # frontend saja
npm run build                                 # build ke frontend/dist
```

## API

| Method | Path | Auth | Fungsi |
|---|---|---|---|
| GET | `/health` | — | Liveness + cek database |
| GET | `/api/v1/scholarships` | — | List/search approved (`q`, `country`, `degree`, `limit`, `offset`) |
| GET | `/api/v1/scholarships/{id}` | — | Detail record publik |
| POST | `/api/v1/recommendations` | — | Matching profil → rekomendasi |
| POST | `/api/v1/matching` | — | Alias dari endpoint di atas |
| GET | `/api/v1/admin/review/*` | Bearer | Queue, detail, metrics, riwayat |
| POST | `/api/v1/admin/review/*` | Bearer | Approve, reject, correct, candidate decision |

Contoh:

```bash
curl -X POST http://localhost:8000/api/v1/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "target_country": "Japan",
    "degree": "Master",
    "field_of_study": ["Computer Science"],
    "current_gpa": 3.5,
    "ielts_score": 7.0,
    "research_experience": "Preferred",
    "work_experience": "Optional",
    "publication": "Not Required",
    "leadership": true,
    "funding_preference": "Fully Funded"
  }'
```

```bash
curl http://localhost:8000/api/v1/admin/review/candidates \
  -H "Authorization: Bearer $POLARIS_ADMIN_TOKEN"
```

---

## Pipeline otomatis (tanpa AI)

Satu perintah menjalankan crawl → enrichment → review deterministik:

```bash
python scripts/pipeline_run.py MY BN DE --max-total-pages 120 --runtime 14
python scripts/pipeline_run.py --all --skip-recent-days 7
```

Menambah negara: [docs/RUNBOOK.md](docs/RUNBOOK.md).

Radar agregator (hanya sebagai penunjuk URL resmi):

```bash
python scripts/harvest_aggregators.py --limit-articles 30 --register
```

## Menjalankan discovery

Country runner punya tiga mode dengan janji yang berbeda:

```bash
# 1. Lihat rencana query. Tidak membuka database, tidak menyentuh jaringan.
python scripts/run_country_exploration.py JP --plan-only

# 2. Simulasi offline. NullSearchProvider, tanpa fetch, semua tulisan di-rollback.
python scripts/run_country_exploration.py JP --dry-run --report

# 3. Live run. Hanya boleh ke database lokal bernama *_test / *_scratch.
python scripts/run_country_exploration.py JP --report --max-runtime 15
```

Live run menolak database yang tidak disposable:

```text
NonScratchDatabase: Refusing to run a live exploration against database 'polaris'.
```

Untuk membuat scratch database:

```bash
createdb polaris_scratch
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/polaris_scratch alembic upgrade head
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/polaris_scratch \
  python scripts/run_country_exploration.py JP --report --max-runtime 10
```

Aggregator runner punya guard sendiri dan **tidak** fallback ke `DATABASE_URL`:

```bash
POLARIS_AGGREGATOR_TEST_DATABASE_URL=postgresql+psycopg://.../polaris_scratch \
  python scripts/run_aggregator_discovery.py --report
```

Metrik run membedakan tahap yang gagal: query, hasil search, kandidat frontier, fetch, page intent, verifikasi sumber, ekstraksi, persistensi, dan record baru di `pending_review`. Baca dari atas ke bawah; jangan menaikkan budget sebelum tahap pertama yang nol diperbaiki.

---

## Status per negara

```bash
python scripts/country_status.py          # semua negara
python scripts/country_status.py JP       # satu negara
python scripts/country_status.py --json   # machine-readable
```

Menampilkan config, jumlah seed, last run, state frontier, sumber, dan katalog per negara.

## Provider-first coverage

`run_country_coverage.py` menjalankan provider discovery → source registration → acquisition. Jalur ini memakai `AcquisitionService` yang sama dengan country exploration, jadi page intent/listing guard/aggregator blocking berlaku.

```bash
python scripts/run_country_coverage.py JP --plan-only
python scripts/run_country_coverage.py JP --max-sources 10 --max-pages 5
```

Live run tetap membutuhkan database `_test`/`_scratch` (atau `--allow-non-scratch`).

## Exhaustive per-country crawl

`run_country_crawl.py` menghabiskan semua sumber aktif untuk satu negara: homepage provider → section beasiswa → halaman program → ekstraksi. Semua record masuk `pending_review`.

```bash
python scripts/run_country_crawl.py JP --plan-only
python scripts/run_country_crawl.py JP --discover --max-total-pages 300
python scripts/run_country_crawl.py JP --skip-recent-days 1 \
  --max-sources 4 --max-pages-per-source 50 --max-total-pages 200
```

Untuk database resmi yang besar, importer khusus menyimpan work list ke batch source:

```bash
python scripts/import_studyinjapan.py --max-pages 30 --register
```

Studi kasus JP: 661 detail URL dari database Study in Japan diproses menjadi 55 record `pending_review`.

---

## Review queue

Kurasi adalah batas publikasi. CLI ini memanggil `ReviewService`, jadi setiap keputusan tetap menulis version row dan audit action — tidak ada jalan pintas ke `extraction_status`.

```bash
# Ringkasan antrean
python scripts/review_queue.py summary

# Daftar record yang menunggu keputusan, dengan gate yang memblokir
python scripts/review_queue.py list --country GB --limit 20

# Publikasikan (wajib --yes; alasan dicatat)
python scripts/review_queue.py approve <scholarship_id> \
  --actor alice --reason "verified against the official page" --yes

# Tolak (alasan wajib)
python scripts/review_queue.py reject <scholarship_id> \
  --actor alice --reason "index page, not one programme" --yes
```

`--override` tersedia untuk field yang memang boleh di-override (degree, funding, field, deadline, GPA); alasan tetap wajib. Tanpa `--yes`, perintah tulis ditolak.

---

## Test

```bash
pytest tests -q
```

Test yang membutuhkan knowledge base development (golden samples, katalog 41 record, pinned captures) ditandai `data` dan di-skip di database bersih. Untuk menjalankannya:

```bash
POLARIS_RUN_DATA_TESTS=1 pytest tests -q
```

Frontend:

```bash
cd frontend
npm test
npx vue-tsc --noEmit
npm run build
```

Lint:

```bash
ruff check .
```

Coverage gate ada di 85% (`pyproject.toml` dan CI memakai angka yang sama).

---

## Migrasi

```bash
alembic upgrade head          # menerapkan
alembic current               # revisi aktif
alembic revision --autogenerate -m "..."   # hanya untuk perubahan model
```

Jangan memakai `Base.metadata.create_all()` di production. Itu alat test; skema production datang dari migrasi.

---

## Deployment

- **Satu origin.** API menyajikan `frontend/dist` dan menangani route SPA (`/discover`, `/match`, `/scholarships/:id`) dengan fallback ke `index.html`. Path `/api/...` yang tidak dikenal tetap 404 JSON.
- **Admin token wajib.** `POLARIS_ADMIN_TOKEN` diset di secret manager. Tanpa token, surface review mengembalikan 503.
- **CORS tertutup secara default.** Isi `POLARIS_ALLOWED_ORIGINS` hanya jika frontend di-host terpisah.
- **Healthcheck.** `/health` mengembalikan 503 saat database tidak terjangkau, sehingga orchestrator tidak mengirim trafik ke API yang tidak bisa melayani.
- **Migrasi saat start.** Entrypoint container menjalankan `alembic upgrade head` sebelum uvicorn.
- **Discovery terpisah dari serving.** Jalankan script discovery sebagai job, bukan di proses API. Image yang sama bisa dipakai: `docker compose run --rm api python scripts/run_country_exploration.py ...`

---

## Batasan yang diketahui

- **Belum ada akun pengguna.** Hanya ada satu bearer token operator untuk permukaan admin. Tidak ada login, sesi, atau peran.
- **Belum ada UI review.** Kurasi dilakukan lewat API admin atau script; antarmuka operator belum dibangun.
- **PDF scanned belum didukung.** PDF dengan text layer diproses; PDF hasil scan butuh OCR dan saat ini dicatat sebagai kegagalan yang jujur.
- **Ekstraksi masih condong bahasa Inggris.** Classifier intent sudah multibahasa, tetapi pola nama/deadline/provider belum setara untuk semua bahasa.
- **Matching deterministik, bukan ML.** Tidak ada model prediksi kelayakan; skor adalah penjumlahan kriteria berbobot.

---

## Dokumen terkait

- [IDEA.md](IDEA.md) — visi produk dan aturan arsitektur
- [docs/v0.1/](docs/v0.1/) — spesifikasi domain, matching, source registry, ADR
- [docs/PROJECT-CODEBASE-REVIEW-AND-NEXT-STEPS.md](docs/PROJECT-CODEBASE-REVIEW-AND-NEXT-STEPS.md) — review codebase dan rekomendasi
- [docs/progress/](docs/progress/) — laporan milestone dan status
