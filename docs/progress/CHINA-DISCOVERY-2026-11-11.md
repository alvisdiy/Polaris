# China Discovery — 11 November 2026

Target: membuat run CN benar-benar menemukan beasiswa, bukan 0 seperti sebelumnya.

Hasil: **15 beasiswa China approved**, dari 0.

---

## 1. Kenapa CN selalu nol

Tiga sebab terpisah, semuanya nyata:

| Sebab | Bukti |
|---|---|
| Situs nasional di belakang WAF | `csc.edu.cn`, `campuschina.org`, `studyinchina.csc.edu.cn` menjawab **HTTP 412** untuk semua klien non-browser, termasuk Playwright headless |
| Katalognya bukan HTML biasa | `campuschina.org/scholarships/index.html` memuat daftar lewat `AjaxHandler_LXZG.ashx` dengan parameter bertanda tangan (`xXixBQbd=…`); halaman kategori `indexdp40–45` hanya berisi teks berita |
| Seed config salah host | `www.campuschina.org` gagal DNS (yang resolve hanya tanpa `www`), dan `csc.edu.cn` 412 — dua dari tiga seed tidak pernah bisa dibuka |

Kesimpulan: menambah user-agent atau retry tidak akan menolong. Katalog nasional CN bukan jalur yang bisa di-crawl.

---

## 2. Jalur yang dipakai

Situs **universitas** China tidak diblokir. Terverifikasi 200:

```
www.tsinghua.edu.cn/en/          english.pku.edu.cn         en.sjtu.edu.cn
iso.fudan.edu.cn                 icz.edu.cn (Zhejiang)      en.sdu.edu.cn
en.whu.edu.cn                    en.nankai.edu.cn           study.tongji.edu.cn
admission.blcu.edu.cn            sie.uibe.edu.cn            study.cqu.edu.cn
iso.hust.edu.cn                  iec.dmu.edu.cn             oec.xmu.edu.cn
```

Ini juga sumber yang **benar** menurut aturan project: penyelenggara beasiswa CSC di China adalah universitas yang menaunginya, dan halaman universitas memuat level, pendanaan, dan deadline.

Dua lapis yang dibangun:

1. **Seed terkurasi** — `configs/countries/CN.json` diisi 11 halaman beasiswa universitas yang terbukti hidup, menggantikan CSC/Campus China yang mati.
2. **Discovery berulang** — `scripts/discover_china.py` menjalankan query `site:edu.cn` / `site:gov.cn`, menyaring host resmi, dan menyimpan hasilnya sebagai work list batch pada `source.scholarship_page_urls`. Pola yang sama dengan importer Study in Japan.

```
python scripts/discover_china.py --queries 8               # lihat hasil
python scripts/discover_china.py --queries 8 --register    # jadi work list
python scripts/run_country_crawl.py CN --source-id <uuid>  # crawl batch itu
```

---

## 3. Bug yang ketemu di jalan

| Bug | Dampak | Perbaikan |
|---|---|---|
| `seed_urls` config negara tidak pernah didaftarkan sebagai source | negara dengan config valid tetap 0 source (FR, CN) | `ensure_seed_sources()` di runner |
| Provider code > 32 karakter | insert gagal di domain panjang (`enseignementsup-recherche.gouv.fr`) | potong + hash 6 karakter |
| Work list importer ditaruh di belakang link discovery | budget halaman habis untuk link tebakan | URL importer diproses lebih dulu |
| Exploration mendaftarkan agregator sebagai source | `wentchina.com` (blog) masuk registry sebagai Active, sejajar universitas | guard `is_blocked_source_host` di titik registrasi; 50 source agregator lama di-retire |
| Seed menandai provider `verified` | klaim trust tanpa verifikasi; mematahkan kontrak discovery | seed sekarang `candidate` |
| Test Phase 2 menguji state global DB | gagal begitu seed universitas ada | test hanya menilai provider yang dibuat run itu |

---

## 4. Review CN

Semua keputusan lewat `review_queue.py`, actor `owner`, dengan `--evidence-url` halaman aslinya.

**Approve (15)** — nama dan level dikoreksi dulu bila perlu:

| Program | Level |
|---|---|
| Chinese Government Scholarship – Bilateral Program (SYSU) | Bachelor, Master, PhD |
| Silk Road Chinese Government Scholarship (SYSU) | Bachelor, Master, PhD |
| Sun Yat-sen University Scholarship for International Students | Bachelor, Master, PhD |
| Shanghai Government Scholarship (SHMTU) | Bachelor, Master, PhD |
| Peking University International Student Scholarship | Bachelor, Master, PhD |
| HIT International Students Scholarship | Bachelor, Master, PhD |
| CGS – High-Level Graduate Program (SHMTU) | Master, PhD |
| 2027 Chinese Government Scholarship – Nankai University | Master, PhD |
| Atomic Energy Scholarship Program of China (SYSU) | Master, PhD |
| The Atomic Energy Scholarship Program of China (Tsinghua) | Master, PhD |
| Youth of Excellence Scheme (SYSU) | Master |
| CGS – Youth of Excellence Scheme (ZJU) | Master |
| Peking University International Chinese Language Teachers Scholarship | Master |
| Application Guidelines for International Chinese Language Teachers Scholarship (SYSU) | Master |
| China Link Short-Term Scientific Exchange (SYSU) | Short Course |

**Reject (5)**: halaman kantor internasional (bukan program), halaman "CLOSED" siklus 2026, program Yuke/pre-university (bukan beasiswa), duplikat PKU.

**Masih pending (6)**: `2026 CGS Application Guide` (CSC), `CGS` dan `Tianjin Government Scholarship` (Tianjin), `Zhejiang Government Scholarship`, dua record dengan konflik deadline. Butuh bukti level/deadline tambahan.

---

## 5. Angka

| Metrik | Sebelum sesi CN | Sesudah |
|---|---:|---:|
| CN approved | 0 | **15** |
| CN total record | 1 | 26 |
| Katalog approved (semua negara) | 84 | **99** |
| Source agregator aktif | 50 | 0 (di-retire) |

Crawl: 12 source pertama → 53 halaman, 14 record; 25 source → 104 halaman; batch discovery → 25 halaman, 7 record; total 146 halaman CN diproses.

Verifikasi API: `GET /api/v1/scholarships?country=China` → 13 record publik (2 sisanya tersaring karena deadlinenya sudah lewat — perilaku yang benar).

---

## 6. Yang belum

1. **Katalog nasional CSC tetap tidak bisa di-crawl**; kalau nanti dibutuhkan, jalurnya adalah API resmi atau data terbuka, bukan scraping.
2. **6 pending CN** butuh bukti tambahan.
3. **Nama provider hasil discovery masih kasar** (`Global`, `Iso`, `En`, `Iczu`, `Yz`) — berasal dari judul halaman, bukan nama institusi.
4. **Confucius Institute & Enterprise scholarships** belum tersentuh; halaman kategorinya statis tanpa daftar.
5. Crawl berikutnya perlu `--skip-recent-days` agar tidak mengulang 146 halaman yang sama.
