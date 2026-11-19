# Per-Country Service Fix — 11 November 2026

**Konteks:** layanan per-country sudah ada, tetapi terdiri dari tiga jalur yang tumpang tindih dan beberapa di antaranya tidak pernah benar-benar bekerja pada data seed.
**Status:** fixed + verified on a scratch database.

---

## 1. Audit: tiga jalur, empat bug

| Jalur | Dipakai oleh | Masalah |
|---|---|---|
| `services/exploration/engine.py` | `run_country_exploration.py` | Jalur modern; sudah benar |
| `services/ingestion/country_orchestrator.py` | `run_global_acquisition.py` | Duplikasi blok connector, URL kosong, tanpa guard |
| `services/ingestion/country_coverage_orchestrator.py` | `run_country_coverage.py` | Provider discovery hardcoded, source tanpa URL, scholarship discovery bypass gate |

Bug yang ditemukan saat dijalankan pada database seed:

1. **Status tidak pernah cocok.** Seed menulis `source_registry.status='active'` dan `provider.verification_status='unverified'`; orchestrator memfilter `"Active"/"Provisional"` dan `discovered/candidate/verified`. Hasilnya: **0 sumber terlihat** padahal database berisi 5 sumber JP.
2. **`Provider.official_url` tidak pernah diisi** oleh `register_source`, sehingga coverage Phase 2 melewati semua provider.
3. **Coverage Phase 3 memakai `DiscoveryOrchestrator` lama**, yang memasukkan setiap URL ke ekstraksi tanpa page intent, listing guard, atau aggregator blocking.
4. **Phase 1 hardcoded `UniversityStrategy`**, jadi config government/foundation tidak pernah dipakai.

---

## 2. Perbaikan

### 2.1 Satu vocabulary lifecycle

`services/domain/lifecycle.py`:

- `Active`, `Provisional`, `Retired` untuk source;
- `discovered`, `candidate`, `verified`, `registered` untuk provider;
- normalisasi input (`"active"` → `"Active"`, `"unverified"` → `"discovered"`);
- `source_is_active()` untuk membaca status lama dengan benar.

`register_source` sekarang:

- menulis `status="Active"` dan `verification_status="discovered"`;
- mengisi `Provider.official_url`;
- menormalkan provider lama yang masih `unverified`.

Query di engine, kedua orchestrator, dan scholarship discovery sekarang memakai `lower(status)` agar data lama tetap terbaca.

### 2.2 Migrasi data

| Revisi | Isi |
|---|---|
| `f6b7c8d9e0a1` | `active` → `Active`, `provisional` → `Provisional`, `unverified` → `discovered` |
| `a7c8d9e0f1b2` | backfill `provider.official_url` dari source dengan prioritas tertinggi |
| `b8d9e0f1a2c3` | retire `https://www.university-scholarships.jp/` (host placeholder yang tidak resolve) |

Bukti di scratch: 13 source menjadi `Active`, 13 provider menjadi `discovered`, 13 provider punya `official_url`.

### 2.3 Coverage memakai jalur modern

- Phase 1: semua `ProviderDiscoveryConfig` aktif diresolusi lewat `StrategyFactory` (bukan hanya University).
- Phase 2: provider tanpa `official_url` atau yang menunjuk agregator/social **dilewati**; sumber hanya dibuat untuk provider yang punya halaman resmi.
- Phase 3: memakai `AcquisitionService` — page intent, listing guard, aggregator blocking, identity dedup, dan review boundary berlaku. Bukan lagi `DiscoveryOrchestrator` lama.

### 2.4 Runner dan observability

- `run_country_coverage.py`: `--plan-only`, scratch guard (`NonScratchDatabase`), `--max-sources`, `--max-pages`.
- `country_status.py`: status per negara — config, seeds, last run, frontier, sources, catalogue.
- `country_orchestrator.py`: blok connector duplikat dihapus, URL kosong/agregator dilewati, ditandai legacy.

---

## 3. Bukti

### 3.1 Coverage JP pada scratch

| Metrik | Sebelum fix | Sesudah fix |
|---|---:|---:|
| `sources_discovered` | 0 | **5** |
| `sources_active` | 0 | **4** |
| `candidate_urls_found` | 0 | **8** |
| `pages_fetched` | 0 | **3** |
| `errors` | 0 | **0** |

(0 record dipersist pada uji 4 sumber × 2 halaman; halaman yang terbaca masih index/overview. Ini yield, bukan bug lifecycle.)

### 3.2 Status per negara

`python scripts/country_status.py` sekarang bisa menjawab pertanyaan "negara X kondisinya bagaimana" tanpa SQL manual:

| Negara | Seeds | Last run | Frontier pending | Sources | Katalog |
|---|---:|---|---:|---|---|
| JP | 3 | completed | 3.047 | 198 verified | 6 approved / 4 pending |
| GB | 3 | completed | 1.590 | 106 verified | 20 approved / 33 pending |
| ID | 3 | completed | 1.849 | 87 verified | 3 approved / 9 pending |
| KR | 3 | completed | 2.259 | 64 verified | 1 pending |
| DE | 3 | completed | 368 | 19 verified | 5 approved / 1 pending |
| SG | 3 | failed | 1.053 | 69 verified | 5 approved / 1 pending |
| AU/CN/FR/US | 3 | — | — | 1–4 | 0–1 approved |

Empat negara punya config dan seed tetapi **belum pernah dijalankan**.

### 3.3 Test

- `ruff check .` bersih.
- **1837 passed, 137 skipped, 0 failed**.
- Test lifecycle/phase-2 diperbarui ke vocabulary kanonik; test lama yang mengunci `unverified`/`active` diperbaiki.

---

## 4. Yang belum

- **AU, CN, FR, US belum pernah run.** Config dan seed sudah ada; tinggal dijalankan di scratch dan diukur.
- **Frontier backlog besar** (JP 3.047, KR 2.259, ID 1.849, GB 1.590). Ini kandidat lama; perlu pruning sebelum menambah volume.
- **Yield program bernama masih rendah.** Coverage 4 sumber menghasilkan 8 kandidat, 3 halaman, 0 record; halaman yang ditemukan masih index/overview. Perlu connector site-specific (studyinjapan search, JSPS, JASSO) atau ekspansi section yang lebih dalam.
- **UI review** belum ada; CLI sudah cukup untuk operator tunggal.

---

## 5. Urutan berikutnya

1. Jalankan `run_country_coverage.py` untuk **FR/CN/AU** di scratch, 3 sumber × 5 halaman; bandingkan funnel.
2. Prune frontier per negara (prioritas 5, domain sosial/direktori) sebelum run berikutnya.
3. Untuk JP/GB yang sudah punya banyak sumber, fokus ke **site-specific connector** dan completion 49 record pending.
