# Polaris — Production Readiness

**Tanggal:** 9 November 2026
**Cakupan:** kesiapan kode, keamanan, packaging, deployment, dan bukti verifikasi.
**Bukan cakupan:** kualitas katalog (lihat [AS-IS recommendation](AS-IS-RECOMMENDATION-2026-11-09.md)).

---

## 1. Ringkasan

Kode sekarang **dapat dideploy** sebagai satu service (API + SPA) dengan Postgres, dan permukaan admin tertutup secara default. Yang belum "production ready" bukan lagi infrastruktur, melainkan **kualitas data dan alur kurasi**: 61% record ditolak reviewer dan 18 record menunggu keputusan (review deterministik sudah otomatis).

Jangan menaikkan volume discovery sebelum dua angka itu membaik.

---

## 2. Yang diperbaiki di pass ini

### Keamanan

| Item | Status | Bukti |
|---|---|---|
| Admin review API tanpa autentikasi | **Fixed** | Bearer token di router; unset = 503, salah = 401 |
| Token dibandingkan konstan-time | **Fixed** | `hmac.compare_digest` di [api/auth.py](../api/auth.py) |
| Guard DB scratch untuk live discovery | **Fixed** | `--plan-only`, `--dry-run` rollback, `NonScratchDatabase` |
| SSRF / robots / prompt injection | Sudah ada | `url_safety`, `robots_rules`, `untrusted` + test security |
| CORS wildcard | Tidak pernah default | Kosong = CORS mati; origin harus eksplisit |

### Correctness

| Item | Status |
|---|---|
| Crash `official_page_url NOT NULL` saat akuisisi | Fixed (fallback ke URL dokumen) |
| `max_candidates` tidak ditegakkan | Fixed |
| Budget domain dihitung dua kali | Fixed (hanya saat fetch) |
| Prioritas query family baru jatuh ke default | Fixed |
| Parser robots first-match (Python 3.11) | Diganti longest-match |
| "No results" dihitung sebagai kegagalan search | Fixed |
| `run_mext_pipeline.py` syntax error | Fixed (async + entry point) |
| Console script `polaris-knowledge` menunjuk modul hilang | Dihapus |
| `pypdf` tidak dideklarasikan | Ditambahkan ke dependency |
| Duplikasi `_FIELD_ALIASES` | Dihapus |
| Docstring skor field tidak sesuai kode | Diperbaiki |

### Test & CI

- `ruff check .` → **0 error** (sebelumnya 171).
- Full suite di database bersih → **1670 passed, 137 skipped, 0 failed**.
- Test yang membutuhkan knowledge base dev ditandai `data` dan di-skip kecuali `POLARIS_RUN_DATA_TESTS=1`.
- Coverage gate disamakan di **85%** (`pyproject.toml` dan CI).
- Bug test lama diperbaiki: `ProviderDiscoveryConfig(config_id=...)`, `status_counts` tanpa key nol, asumsi constraint legacy.

### Frontend

- `npm run build` → sukses.
- `vue-tsc --noEmit` → sukses.
- `npm test` → 20 test lulus.

### Deployment

- `Dockerfile` multi-stage: build SPA → image Python + Chromium.
- `docker-compose.yml`: Postgres 16 + API, healthcheck, migrasi saat start.
- `scripts/docker-entrypoint.sh`: `alembic upgrade head` lalu uvicorn.
- `.dockerignore` mencegah `.env`, test, dan node_modules masuk image.
- `README.md`: quickstart Docker dan lokal, env vars, API, discovery modes, batasan.

---

## 3. Bukti verifikasi

```text
ruff check .                         All checks passed
pytest tests -q                      1670 passed, 137 skipped
frontend: npm test                   20 passed
frontend: vue-tsc --noEmit           exit 0
frontend: npm run build              built in ~3s
pip wheel .                          api/ 8, services/ 94, database/ 40 di dalam wheel
docker compose config                valid
```

Catatan: `docker build` **belum dijalankan** di mesin ini karena daemon Docker Desktop tidak aktif (`dockerDesktopLinuxEngine` pipe tidak tersedia). Dockerfile dan compose sudah divalidasi secara konfigurasi, tetapi build image harus diuji di host dengan daemon aktif sebelum go-live.

Smoke test terhadap uvicorn + Postgres:

| Request | Hasil |
|---|---|
| `GET /health` | 200 `{"status":"ok","database":"ok"}` |
| `GET /api/v1/scholarships` | 200 |
| `GET /api/v1/admin/review/candidates` tanpa token | 401 |
| `GET /api/v1/admin/review/candidates` token salah | 401 |
| `GET /api/v1/admin/review/candidates` token benar | 200 |
| `POST /api/v1/recommendations` | 200 |
| `GET /api/v1/nope` | 404 JSON |
| `GET /discover` | 200 SPA shell |

---

## 4. Checklist go-live

### Wajib sebelum trafik

- [ ] `POLARIS_ADMIN_TOKEN` digenerate acak (≥32 byte) dan disimpan di secret manager.
- [ ] `DATABASE_URL` menunjuk Postgres production, bukan `polaris` lokal.
- [ ] `alembic upgrade head` dijalankan (entrypoint container sudah melakukannya).
- [ ] TLS dipasang di reverse proxy; API tidak diekspos lewat HTTP publik.
- [ ] `POLARIS_ALLOWED_ORIGINS` diisi hanya jika frontend di-host terpisah.
- [ ] Backup harian Postgres + uji restore.
- [ ] Log dikirim ke collector; `/health` dipantau.

### Disarankan

- [ ] Rate limit di reverse proxy untuk `POST /api/v1/recommendations` dan `/api/v1/admin/*`.
- [ ] Alert jika `/health` 503 > 2 menit.
- [ ] Alert jika record `pending_review` > 7 hari.
- [ ] Job discovery dijadwalkan terpisah dari proses API, ke database scratch lalu dipromosikan lewat review.
- [ ] Rotasi token admin (belum ada endpoint rotasi; restart dengan env baru).

---

## 5. Sisa gap (jujur)

| Gap | Dampak | Status |
|---|---|---|
| Presisi ekstraksi (halaman Topics/index lolos) | Gate label section, policy generik, agregator, dan platform sosial sudah ada (10 Nov 2026); penemuan program bernama masih tipis | **Sebagian selesai** — lihat [precision gate report](progress/PRECISION-GATE-2026-11-10.md) |
| Backlog review 18 record | Katalog tidak tumbuh | Ditangani `scripts/pipeline_run.py` (auto-review) |
| Kelengkapan deadline/funding (51%/41%) | Matching dan filter lemah | Data, rencana P1-A |
| Belum ada UI review | CLI review tersedia (`scripts/review_queue.py`); UI belum | Tidak blocking untuk single operator |
| Belum ada akun pengguna | Satu token operator | Tidak blocking untuk internal |
| PDF scanned tanpa OCR | Sebagian sumber Jepang tidak terbaca | Dicatat sebagai kegagalan, bukan crash |
| Ekstraksi multilingual belum setara | Yield JP/KR/ZH lebih rendah | Backlog |
| Belum ada metrics Prometheus | Observability hanya log | Disarankan sebelum skala |
| Working tree besar belum di-commit | Sulit audit perubahan | Disarankan commit per milestone |

---

## 6. Runbook singkat

```bash
# Deploy
export POLARIS_ADMIN_TOKEN=$(python -c "import secrets; print(secrets.token_hex(32))")
docker compose up -d --build

# Cek
curl -fsS http://localhost:8000/health

# Migrasi manual (jika di luar container)
alembic upgrade head

# Discovery aman
python scripts/run_country_exploration.py JP --plan-only
python scripts/run_country_exploration.py JP --dry-run --report
DATABASE_URL=...polaris_scratch python scripts/run_country_exploration.py JP --report --max-runtime 10

# Review queue
python scripts/review_queue.py summary
python scripts/review_queue.py list --country JP --limit 20
python scripts/review_queue.py approve <id> --actor alice --reason "verified" --yes
python scripts/review_queue.py reject <id> --actor alice --reason "index page" --yes
```

---

## 7. Kesimpulan

**Infrastruktur: siap.** API, auth admin, migrasi, container, healthcheck, test suite, dan dokumentasi sudah konsisten.

**Data: belum siap untuk skala.** Presisi dan throughput review adalah pekerjaan berikutnya, dan itu tidak diselesaikan dengan menambah crawler atau negara.
