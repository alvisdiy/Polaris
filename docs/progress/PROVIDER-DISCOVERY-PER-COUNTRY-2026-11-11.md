# Provider Discovery per Country — 11 November 2026

**Konteks:** permintaan "per country harusnya ada beasiswa dari kampus atau pemerintah" sudah dijelaskan di dokumen desain. Implementasinya belum mengikuti dokumen itu.
**Status:** gap utama ditutup; yield masih pekerjaan terpisah.

---

## 1. Apa kata dokumen

`docs/v0.1/provider-discovery-specification.md`:

- Country adalah dimensi utama, bukan provider yang sudah dikenal.
- Discovery surface yang sah: **government portal, education directory, scholarship agency, university directory**.
- Strategi: `link_discovery`, `sitemap_discovery`, `structured_directory`, hybrid.
- Verifikasi: TLD resmi → reachability → content → **type inference** (`.go.*` = Government, `.ac.*` = University, `.org` = NGO/review) → dedup.
- Konfigurasi disimpan di database (`ProviderDiscoveryConfig`), bukan hardcode.

`docs/v0.1/data-aquitition-strategy.md`:

- Priority 1 Government, Priority 2 Official University, Priority 3 Foundation.
- Blog/forum/Reddit/Facebook/TikTok/YouTube bukan sumber.
- Third-party educational website hanya referensi, bukan sumber resmi.

`docs/progress/SCHOLARSHIP-DISCOVERY-EXPANSION.md`:

- Provider coverage seharusnya mencakup government, university, foundation, international organisation.

---

## 2. Gap yang ditemukan

| # | Gap | Bukti |
|---|---|---|
| 1 | `provider_discovery_config` **0 baris** di database | seed script ada, tidak pernah dijalankan |
| 2 | `StrategyFactory` hanya punya `UniversityStrategy` | pemerintah/foundation tidak punya jalur |
| 3 | Semua config default `organization_type="University"` | JASSO/MEXT diperlakukan sebagai universitas |
| 4 | Surface US/KR/ID/CN memakai **Wikipedia** | melanggar official-source-first |
| 5 | `provider_code` = hash URL penuh | satu domain dengan dua path = dua provider |
| 6 | Tidak ada type inference per link | universitas di halaman MEXT dilabeli Government |

---

## 3. Perbaikan

### 3.1 Satu strategy generik untuk semua tipe

`services/ingestion/ecosystem_strategies/link_discovery.py`:

- `LinkDiscoveryStrategy` — fetch surface, filter TLD resmi + blocklist agregator/social, satu provider per **registered domain**;
- subclass: `UniversityStrategy`, `GovernmentStrategy`, `FoundationStrategy`, `ScholarshipAgencyStrategy`, `ResearchInstitutionStrategy`;
- `university_strategy.py` tetap ada sebagai re-export agar import lama tidak pecah.

### 3.2 Type inference per domain

Urutan:

1. domain yang sama dengan surface → tipe surface (JASSO tetap Scholarship Agency meski `.go.jp`);
2. suffix government (`.go.jp`, `.gov.uk`, `.gouv.fr`, `.go.kr`, `.go.id`, …) → Government;
3. suffix academic (`.ac.jp`, `.edu.cn`, `.ac.uk`, `.edu.au`, …) → University;
4. `foundation`/`stiftung` di domain → Foundation;
5. `.org`/`.or.*` → NGO;
6. fallback ke tipe surface.

### 3.3 Identity provider = domain

`_provider_code_from_url` sekarang memakai registered domain, bukan hash URL penuh. Dua halaman dari satu universitas menjadi satu Provider; halamannya menjadi sources.

### 3.4 Seed 22 surface resmi

`scripts/seed_provider_discovery_config.py`:

- **16 Government** + **6 Scholarship Agency**;
- surface: MEXT, JASSO, Study in Japan, JSPS, DAAD, BMBF, Research in Germany, Chevening, British Council, UKCISA, EducationUSA, Fulbright, Study in Korea, GKS, LPDP, Kemdikbud, Campus France, MESR, Study Australia, Australia Awards, Campus China, CSC;
- TLD resmi diambil dari `configs/countries/*.json` (`soft_domain_signals`), bukan duplikasi;
- Wikipedia dihapus dari US/KR/ID/CN;
- idempotent: country + surface yang sama di-update, bukan diduplikasi.

Jalankan setelah country tersedia:

```bash
python scripts/seed_provider_discovery_config.py
```

---

## 4. Bukti

JP coverage pada scratch (`run_country_coverage.py JP --max-sources 3 --max-pages 1`):

| Metrik | Sebelum provider discovery | Sesudah |
|---|---:|---:|
| Provider ditemukan | 0 | **4** |
| Provider terverifikasi | 0 | **4** |
| Sumber ditemukan | 0 | **9** |
| Sumber aktif | 0 | **8** |
| Kandidat | 0 | **26** |
| Halaman | 0 | **7** |
| Error | 0 | **0** |

Tipe provider setelah run:

| Tipe | Jumlah |
|---|---:|
| Government | 13 |
| Scholarship Agency | 2 |
| University | 1 |
| Foundation | 1 |

Config tersimpan: **22** (16 Government, 6 Scholarship Agency).

Test: **1841 passed**, lint bersih.

---

## 5. Yang belum

- **University directory resmi belum menjadi surface tersendiri.** Universitas saat ini ditemukan sebagai link dari portal pemerintah/agency. Dokumen menyebut `university_directory`; surface seperti university search Study in Japan, EducationUSA, Study in Korea, Campus China perlu ditambahkan sebagai config `organization_type="University"`.
- **0 record dipersist** dari 7 halaman. Halaman yang ditemukan masih index/overview; ini bottleneck yield, bukan provider discovery.
- **FR/CN/AU belum pernah dijalankan** meski config + seed sudah ada.
- **Verifikasi provider** masih menghasilkan `candidate`; sumber baru berstatus Provisional sampai reviewer/verifikasi.
- **Sitemap/structured strategies** belum diimplementasikan; saat ini semua `link_discovery`.

---

## 6. Urutan berikutnya

1. Tambah **university directory surfaces** resmi per negara (bukan Wikipedia), lalu jalankan coverage FR/CN/AU.
2. Untuk JP/GB, fokus ke **site-specific connector** (studyinjapan search, JSPS, JASSO) karena provider discovery sudah menemukan sumbernya.
3. Prune frontier per negara sebelum menambah volume.
