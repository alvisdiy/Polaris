# Polaris — Rekomendasi Berdasarkan Kondisi As-Is

**Tanggal:** 9 November 2026
**Snapshot:** DB development (read-only) + 2 live run di `polaris_scratch` setelah perbaikan funnel.
**Sifat dokumen:** rekomendasi keputusan, bukan daftar keinginan. Setiap angka diambil dari database atau run yang bisa direproduksi.

---

## 1. Ringkasan eksekutif

Funnel pencarian sudah **tembus end-to-end**: dua live run JP menghasilkan record nyata di `pending_review`, setelah diperbaiki crash `official_page_url` yang sebelumnya membatalkan seluruh akuisisi sumber.

Konsekuensinya, bottleneck sudah **pindah**. Masalah utama Polaris sekarang bukan "belum bisa menemukan beasiswa", tetapi:

1. **Presisi** — pipeline dan reviewer tidak sepakat tentang apa yang disebut beasiswa.
2. **Throughput review** — antrean 60 record berumur 2–5 minggu, sementara 10.166 kandidat masih menunggu di frontier.
3. **Kelengkapan data** — matching kekurangan bahan: hanya 21 dari 41 record approved punya deadline.

> **Rekomendasi utama: berhenti melebarkan funnel. Konversi yang sudah ditemukan menjadi record yang layak publikasi.**

Menambah negara, crawler, atau volume run sekarang hanya akan memperbesar antrean rejection. Urutan kerja yang benar adalah **presisi → throughput review → kelengkapan → baru skala**.

---

## 2. Bukti as-is

### 2.1 Katalog dan review

| Metrik | Nilai |
|---|---:|
| Total record | 259 |
| Approved (publik) | 41 |
| Pending review | 60 |
| Rejected | 157 |
| Needs correction | 1 |
| **Approval rate dari yang sudah diputuskan** | **20,7%** (41/198) |
| **Rejection rate** | **79,3%** (157/198) |

Review action yang tercatat: 157 `rejected`, 105 `submitted`, 24 `approved`, 21 `corrected`, 4 `candidate_proposed`.

### 2.2 Umur antrean

| Metrik | Nilai |
|---|---|
| Record pending paling tua | 4 Oktober 2026 (36 hari) |
| Record pending terbaru | 25 Oktober 2026 (15 hari) |
| Jumlah pending | 60 |

Tidak ada record pending yang lebih baru dari 25 Oktober. Artinya antrean **berhenti diproses**, bukan sekadar tumbuh lambat.

### 2.3 Kelengkapan record approved (n = 41)

| Field | Terisi | Persentase |
|---|---:|---:|
| Degree | 35 | 85% |
| Funding type | 17 | **41%** |
| Field of study | 28 | 68% |
| Application URL | 40 | 98% |
| **Deadline** | **21** | **51%** |
| Deadline state `active` | 20 | 49% |

Matching memberi bobot 15 untuk GPA dan 10 untuk language, tetapi field yang menentukan kelayakan (deadline, funding) justru yang paling sering kosong. Skor matching saat ini lebih rapi daripada datanya.

### 2.4 Distribusi negara

| Negara | Approved | Pending |
|---|---:|---:|
| United Kingdom | 19 | 41 |
| Japan | 6 | 7 |
| Germany | 5 | 1 |
| Singapore | 5 | 1 |
| Indonesia | 3 | 9 |
| Australia / US / France | 1 each | — |
| South Korea | — | 1 |

UK mendominasi katalog **dan** antrean. JP adalah negara kedua yang paling produktif setelah perbaikan funnel.

### 2.5 Inventaris sumber dan frontier

| Metrik | Nilai |
|---|---:|
| Source terverifikasi | 545 |
| Source needs review | 721 |
| Source belum pernah dicoba (`acquisition_state` NULL) | 879 |
| Source `no_scholarship_pages` | 306 |
| Source `acquired` | 83 |
| Source `failed` | 7 |
| **Frontier pending** | **10.166** |
| Frontier done | 2.487 |
| Frontier rejected | 1.069 |

Ada 545 sumber terverifikasi, tetapi baru 83 yang benar-benar menghasilkan halaman. Bottleneck-nya **konversi sumber menjadi halaman beasiswa**, bukan penemuan sumber baru.

### 2.6 Bukti run live (scratch, JP)

| Metrik | Run 1 (sebelum fix persistensi) | Run 2 (sesudah) |
|---|---:|---:|
| Search results | 28 | 38 |
| Kandidat baru | 214 | 116 |
| Halaman di-fetch | 20 | 14 |
| Peluang tertahan | 11 | 13 |
| Sumber terverifikasi | 6 | 5 |
| **Beasiswa tersimpan** | **0** | **1** (+2 duplikat) |
| Record masuk `pending_review` | 0 | 1 |

Di luar run, satu sumber (Japan Foundation NY) diverifikasi ulang secara manual setelah fix: 1 halaman detail, 1 ekstraksi, 1 record tersimpan.

Contoh record yang lolos: `JSPS Topics` (confidence 0.92, gate `degree`) dan `2027-2028 Fellowship Categories` (confidence 0.70). Keduanya **bukan nama program yang baik** — ini bukti langsung masalah presisi.

---

## 3. Diagnosis

### 3.1 Presisi: definisi "beasiswa" berbeda antara pipeline dan reviewer

Rejection 79% bukan kegagalan acak. Penyebab yang sudah terlihat:

- **Halaman index/topics/overview lolos sebagai `SCHOLARSHIP_DETAIL`.** `JSPS Topics` adalah halaman daftar, bukan satu program.
- **Nama programme sering diambil dari heading section**, bukan dari identitas program.
- **Provider identity lemah**: record Japan Foundation mendapat provider `Jpf` — kode tiga huruf, bukan organisasi.
- **Listing guard** sudah ada, tetapi belum menangkap bentuk "Topics", "Categories", "Archive" yang lazim di portal Jepang.

Konsekuensi: setiap penambahan volume akan menambah rejection dengan proporsi yang sama. **Skala sebelum presisi adalah penggandaan pekerjaan review.**

### 3.2 Throughput: antrean lebih tua daripada data

60 record pending berumur 15–36 hari, dan tidak ada yang masuk setelah 25 Oktober. Penyebabnya bukan hanya kualitas data: **tidak ada alur kerja review yang efisien**. `ReviewService` sudah lengkap (approve/reject/correct, audit, version), tetapi belum ada antarmuka operator untuk memutuskan banyak record dengan bukti di depan mata.

Tanpa perbaikan di sini, presisi yang naik pun tetap berujung di antrean yang sama.

### 3.3 Kelengkapan: matching butuh field yang jarang terisi

Hanya 51% record approved punya deadline, 41% punya funding type. Artinya:

- Filter deadline (satu-satunya hard filter matching) tidak bisa diandalkan.
- Bobot funding 5 poin sering diberikan sebagai "full score" karena field kosong, bukan karena cocok.
- Perbandingan beasiswa di UI akan bolong di kolom yang paling penting.

### 3.4 Inventaris: 10.166 kandidat pending adalah liabilitas, bukan aset

Dengan `max_pages=300` per run, antrean itu butuh ~34 run untuk dikosongkan. Sebagian besar adalah ekspansi link prioritas 5 (situs sosial, direktori, halaman fakultas). Menjalankan lebih banyak run tanpa pruning hanya memindahkan biaya ke fetch dan review.

---

## 4. Rekomendasi berurutan

### P0-A — Precision gate sebelum review (2 minggu)

**Tujuan:** record yang masuk `pending_review` memang satu program beasiswa, dengan nama dan provider yang bisa dipertahankan.

Pekerjaan:

1. `services/exploration/page_intent.py`: tambah sinyal negatif untuk halaman koleksi — `topics`, `categories`, `archive`, `all scholarships`, `scholarship list`, `FAQ`, `news`. Halaman seperti ini harus `SCHOLARSHIP_INDEX`/`OVERVIEW`, bukan `DETAIL`.
2. `services/exploration/listing_guard.py`: perluas family sinyal untuk portal Jepang/Korea (mis. `奨学金一覧`, `トピックス`).
3. `services/ingestion/extraction_quality.py`: tolak nama yang mengandung kata section (`Topics`, `Categories`, `Program Guidelines`, `About Us`) dan utamakan `h1`/programme noun phrase.
4. `services/exploration/provider_resolver.py`: tolak nama organisasi < 4 karakter / akronim tanpa domain; provider harus punya nama atau registered domain.
5. Ukur pada **50 kandidat tetap** (bukan 50 run baru): berapa yang reviewer setujui.

**Acceptance:**

- Approval rate pada sampel baru ≥ 50% (dari 20,7%).
- Rejection rate ≤ 40%.
- Nol record dengan nama bertipe `Topics`/`Categories`/`Guidelines`.
- Nol provider berupa akronim 3 huruf tanpa nama organisasi.

### P0-B — Alur review yang bisa mengosongkan antrean (1 minggu)

**Tujuan:** 60 record lama diputuskan, dan record baru tidak menumpuk lebih dari 7 hari.

Pekerjaan:

1. `scripts/review_queue.py`: daftar record pending dengan kolom keputusan — nama, provider, negara, deadline, confidence, blocking gates, URL bukti, dan alasan penolakan otomatis.
2. Mode `--approve`, `--reject --reason`, `--correct` yang memanggil `ReviewService` (bukan menulis DB langsung), sehingga audit + version tetap tercatat.
3. Ringkasan harian: jumlah pending, umur tertua, approval rate 7 hari terakhir.

**Acceptance:**

- Backlog < 7 hari.
- Waktu keputusan rata-rata < 5 menit/record.
- Setiap keputusan punya `actor` dan `reason`.

### P1-A — Kelengkapan katalog (1 minggu)

**Tujuan:** matching dan UI punya bahan.

Pekerjaan:

1. Verifikasi ulang 41 record approved terhadap halaman resminya; isi deadline/funding/degree yang kosong lewat **candidate revision** yang sudah ada (`ReviewService.propose_candidate` → approve), bukan update langsung.
2. Prioritaskan 20 record yang tidak punya deadline dan 24 yang tidak punya funding.
3. Setelah completeness naik, baru pertimbangkan filter funding/field/deadline di API dan UI.

**Acceptance:**

- Deadline ≥ 80% (dari 51%).
- Funding type ≥ 70% (dari 41%).
- Degree ≥ 90% (dari 85%).
- Tidak ada record approved yang diubah tanpa version + audit row.

### P1-B — Konversi sumber menjadi halaman (2 minggu, setelah P0-A)

**Tujuan:** 306 sumber `no_scholarship_pages` dan 545 sumber terverifikasi menghasilkan halaman detail.

Pekerjaan:

1. Untuk sumber dengan `no_scholarship_pages`, ekspansi satu level lebih dalam (section → listing → detail), dibatasi 3 section seperti sekarang.
2. Ukur `detail_pages_found / verified_sources_attempted`.
3. PDF: hanya proses yang punya text layer; scanned PDF dicatat sebagai `no_text_layer`, bukan error berulang.
4. Prune frontier: buang kandidat prioritas 5 yang berasal dari domain sosial/direktori, dan batasi `pending` per negara.

**Acceptance:**

- ≥ 1,5 halaman detail per sumber terverifikasi yang dicoba.
- Frontier pending turun di bawah 3.000.
- Tidak ada retry infinit pada PDF scanned.

### P2 — Fokus negara dan higiene engineering

1. **Fokus UK + JP** sampai approval rate stabil. UK punya 19 approved/41 pending; JP 6/7. Jangan tambah negara dulu.
2. Isi `README.md`: quickstart, env, cara unit test tanpa DB, cara scratch run, tautan dokumen yang masih berlaku.
3. Tandai test yang butuh knowledge base dev (`@pytest.mark.data`) dan skip di DB kosong; samakan gate coverage (`pyproject` 85 vs CI 90).
4. Commit working tree (256 file) dalam commit logis per milestone, bukan satu commit raksasa.

---

## 5. Yang jangan dilakukan sekarang

| Jangan | Alasan |
|---|---|
| Menambah negara/crawler/volume run | Memperbesar rejection 79% yang sudah ada |
| LLM extraction | Ekstraksi deterministik sedang bekerja; LLM menambah risiko fakta karangan tanpa menyelesaikan presisi nama |
| Auth, application tracking, dashboard | Belum ada masalah yang dipecahkan; katalog belum lengkap |
| Redesign arsitektur / microservices | IDEA.md sudah melarang; bottleneck ada di data, bukan struktur |
| Menurunkan quality gate agar approval naik | Itu memindahkan masalah ke pengguna |

---

## 6. Rencana 10 hari kerja

| Hari | Pekerjaan | Output |
|---|---|---|
| 1–2 | Instrumentasi presisi: ekspor 60 pending + alasan otomatis; klasifikasi penyebab rejection | Baseline 50 sampel |
| 3–5 | Perbaikan `page_intent`, `listing_guard`, `extraction_quality`, `provider_resolver` + test | Precision gate v1 |
| 6–7 | `scripts/review_queue.py` + keputusan 60 record lama | Backlog < 7 hari |
| 8–9 | Verifikasi ulang 41 approved via candidate revision | Completeness naik |
| 10 | Benchmark 3 negara di scratch (UK/JP/SG), 1 run masing-masing | Keputusan scale / tidak |

---

## 7. Gerbang keputusan (go / no-go)

Skala ke negara baru **hanya jika**:

- Approval rate record baru ≥ 50%.
- Backlog review < 7 hari.
- Deadline completeness ≥ 80%.
- ≥ 1,5 halaman detail per sumber terverifikasi.

Jika salah satu gagal: perbaiki tahap pertama yang gagal, **jangan** menambah volume. Ini aturan yang sama yang sudah ditulis di `docs/PROJECT-CODEBASE-REVIEW-AND-NEXT-STEPS.md`, sekarang dengan angka.

---

## 8. Risiko

| Risiko | Mitigasi |
|---|---|
| Perbaikan presisi menurunkan yield | Diterima: yield turun lebih murah daripada review 79% rejection |
| Record lama di frontend berubah status | Hanya lewat candidate revision + audit; tidak ada update langsung |
| 10.166 frontier berisi URL mati | Prune + retry policy; jangan fetch ulang yang sudah `rejected` |
| PDF scanned memakan budget | Deteksi text layer sebelum OCR; catat sebagai kategori tersendiri |
| Test data-dependent menyembunyikan regresi | Marker `data` + jalankan full suite di DB dev sebelum rilis |

---

## 9. Satu kalimat

**Polaris tidak butuh lebih banyak beasiswa ditemukan; ia butuh beasiswa yang sudah ditemukan berubah menjadi record yang layak dipercaya.**
