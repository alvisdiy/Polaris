# Catalogue Integrity — 12 November 2026

Pertanyaan yang dijawab: **lanjut discovery atau design website?**

Jawabannya bukan keduanya. Yang menghalangi produk terlihat layak adalah
**integritas katalog**, dan itu terlihat dari tiga angka:

| Temuan | Angka |
|---|---|
| Record approved yang providernya bukan institusi penyelenggara | 37 dari 99 |
| Record approved tanpa deadline | 74 dari 99 |
| Record approved yang sumbernya job board (`jobs.ac.uk`) | 8 |

Frontend-nya sendiri sudah jadi: 8 halaman (Discover, Match, Compare, Detail,
Saved, About, 404). Menambah halaman tidak akan menutupi provider bernama "Sp"
atau beasiswa tanpa deadline.

---

## 1. Provider: dari artefak crawler jadi institusi

Nama provider sebelumnya datang dari judul halaman, jadi yang tampil ke pengguna
adalah sisa proses, bukan organisasi:

| Sebelum | Sesudah |
|---|---|
| `Bbk` | Birkbeck, University of London |
| `Raeng` | Royal Academy of Engineering |
| `Sp` | Singapore Polytechnic |
| `Iczu` | Zhejiang University |
| `pku.edu.cn` / `sysu.edu.cn` / `shmtu.edu.cn` / `tsinghua.edu.cn` | Peking University / Sun Yat-sen University / Shanghai Maritime University / Tsinghua University |
| `campusfrance.org` (duplikat) | Campus France (satu baris) |
| `Chinese universities (scholarship pages)` | Nankai University, Harbin Institute of Technology |

Selain itu **10 record Jepang** yang providernya MEXT dipindahkan ke universitas
penyelenggaranya: Sophia University, Tokyo Woman's Christian University,
Kokugakuin University, Tama Art University (2), Meiji University, Meiji Gakuin
University, Hamamatsu University School of Medicine, Fukushima University, dan
Toyo University (Masajuro Shiokawa Scholarship — halaman menyebut Toyo University
sebagai pendirinya).

Semua perubahan lewat `ReviewService.correct()` dengan `requeue=False`, jadi
record tetap terbit, tapi setiap perubahan punya audit + alasan + evidence URL.

Yang **sengaja tidak diubah**: 4 MEXT Scholarship (memang pemerintah Jepang) dan
14 record yayasan/perusahaan (Otsuka Toshimi, INPEX, JEES, NIKOH SANGYO, dst).
Provider yang benar untuk itu bukan universitas, dan menebaknya akan mengulang
kesalahan yang sama dengan arah sebaliknya.

---

## 2. Delapan record dari job board ditarik

`jobs.ac.uk` adalah papan lowongan akademik, bukan halaman penyelenggara. Di
bawah aturan *official-source-first* record itu tidak boleh terbit, jadi
kedelapannya di-reject dengan alasan tercatat — bukan diperbaiki diam-diam,
karena halaman resmi universitanya tidak kita punya.

---

## 3. Deadline: extractor-nya yang buta, bukan halamannya

Diagnosis awal: 74 record tanpa deadline. Setelah diperiksa, banyak halaman
**mencantumkan** deadline dengan bentuk yang tidak diterima extractor:

```
Deadline: Friday 4 December 2026.
deadline: noon on Tuesday 2nd December 2026
apply by 1pm (UK time) on Monday 1 June 2026
deadline of 5pm (UK time) on Monday 22 March 2027
- 15 December 2026: Application deadline
```

Penyebabnya: pola hanya menerima `[:\s]+` antara kata kunci dan tanggal. Tidak
ada weekday, jam, timezone, atau kata penghubung.

Perbaikannya sengaja **tertutup**, bukan "teks apa pun":

- filler hanya weekday, jam (`1pm`, `noon`), timezone (`(UK time)`), dan kata
  fungsi (`of`, `on`, `at`, `by`, `until`, `to`, `is`, `for`, `and`);
- jarak tanggal ke kata kunci dibatasi 60 karakter;
- pola "tanggal dulu, lalu kata deadline" ditambah untuk bentuk kalender.

Efeknya diuji dua arah: lima bentuk di atas sekarang terbaca, sementara
`deadline, i.e. have defended their PhD thesis between December 2021 and
December 2026` tetap **bukan** deadline.

Dari 74 record tanpa deadline, 3 berhasil dipulihkan dan diterapkan
(`MOPGA 2027` → 2026-12-15, `International Postgraduate Scholarship 2027` →
2027-03-22, `Allan and Nesta Ferguson` → 2026-06-01 yang sudah lewat sehingga
record itu benar menjadi *expired*). Sisanya memang tidak menyebut tanggal di
halamannya — halaman universitas Jepang biasanya menyuruh menghubungi kampus.

---

## 4. Angka setelah pembersihan

| Metrik | Sebelum | Sesudah |
|---|---:|---:|
| Approved | 99 | **91** |
| Rejected | 197 | 205 |
| Pending | 43 | 43 |
| Total | 340 | 340 |
| Katalog publik (API) | 97 | **89** |
| Record provider non-institusi | 37 | **18** |
| Record publik dari job board | 8 | **0** |
| Record publik dengan deadline | 22 | **25** |

Turunnya approved adalah hasil yang benar: 8 record yang tidak memenuhi aturan
sumber ditarik, dan 1 record menjadi *expired* karena deadlinenya ternyata sudah
lewat.

---

## 5. Test

```
1864 passed, 131 skipped, 0 failed
ruff check . → All checks passed
```

Test baru di `tests/unit/test_real_extractor.py`: lima bentuk deadline nyata,
satu kasus negatif (tanggal di klausa lain), dan satu kasus halaman tanpa tanggal.

---

## 6. Jadi, lanjut ke mana?

Urutannya menurut dampak ke pengguna:

1. **43 pending** — 20 GB, 8 JP, 6 ID, 1 DE, 1 SG, 1 KR dan 6 CN. Ini katalog
   yang sudah ditemukan tapi belum diputuskan; setiap review menambah record
   tanpa biaya crawl.
2. **Kelengkapan field** — 65 dari 91 approved tanpa `funding_type`, 66 tanpa
   deadline. Filter dan matching bergantung pada dua field ini, jadi UI akan
   terasa kosong selama angkanya begini.
3. **Design pass** — setelah dua di atas, karena desain yang baik di atas data
   yang bolong hanya memperjelas kebolongannya.
4. **Discovery negara baru** — paling akhir, karena menambah record ke katalog
   yang belum selesai direview hanya menambah backlog.

Rekomendasi: **review 43 pending dulu**, lalu lengkapi funding/deadline, baru
design.
