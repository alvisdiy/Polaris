# Polaris Current Status

**Snapshot:** 9 November 2026

## Current milestone

Production-readiness pass (infrastruktur) di atas funnel discovery yang sudah diperbaiki.

## Implemented and verified

- Discovery funnel berjalan end-to-end di scratch database: live run JP menghasilkan record nyata di `pending_review`.
- Matching deterministik: filter deadline → scoring berbobot → ranking → explanation.
- API publik: `/api/v1/scholarships`, `/api/v1/scholarships/{id}`, `/api/v1/recommendations`, `/api/v1/matching`.
- Admin review API dengan bearer token wajib; unset = 503, salah = 401.
- Review state machine + audit trail + candidate revision.
- Migrasi Alembic 18 revisi, berjalan dari database kosong.
- Test suite: 1670 passed, 137 skipped (data tests) di database bersih.
- Lint: `ruff check .` bersih.
- Frontend Vue 3: build, typecheck, dan 20 test lulus.
- Docker: multi-stage image + compose (Postgres 16 + API), migrasi saat start, healthcheck.
- Review CLI: `scripts/review_queue.py` (list/summary/approve/reject lewat `ReviewService`, audit + version tetap tercatat).
- Packaging: `pip wheel .` menghasilkan wheel yang memuat `api/`, `services/`, `database/`.

## Known constraints

- Precision gate sudah ditambahkan (10 Nov 2026): label section, policy generik, agregator, dan platform sosial ditolak. Bukti dan batasnya ada di [precision gate report](progress/PRECISION-GATE-2026-11-10.md).
- Penemuan **program bernama** masih tipis: sebagian besar halaman resmi yang ditemukan adalah index/overview, bukan detail program.
- Backlog review 13 record.
- Kelengkapan katalog: 43/142 punya deadline, 39/142 punya funding type, 107/142 punya degree.
- Belum ada akun pengguna; hanya satu token operator.
- Belum ada UI review; kurasi lewat API/CLI.
- PDF scanned belum didukung (butuh OCR).
- Ekstraksi multilingual belum setara.

## Next

Urutan kerja ada di [AS-IS recommendation](progress/AS-IS-RECOMMENDATION-2026-11-09.md):

1. Precision gate (P0-A).
2. Alur review untuk mengosongkan antrean (P0-B).
3. Kelengkapan katalog lewat candidate revision (P1-A).
4. Konversi sumber menjadi halaman (P1-B).
5. Baru skala negara.

## Production readiness

Checklist dan runbook: [PRODUCTION-READINESS.md](PRODUCTION-READINESS.md).

## Historical reports

Laporan milestone lama tetap disimpan di [docs/progress/](progress/) dan [docs/v0.1/](v0.1/). Angka di dalamnya adalah potret pada saat ditulis, bukan keadaan sekarang.
