# Aggregator Radar — 13 November 2026

Pertanyaan: boleh tidak mencari beasiswa dari situs pengumpul seperti
fullyscholarships.com, glornoscholarships.com, opportunitiescircle.com?

Jawaban: **boleh, tapi hanya sebagai radar.** Mereka menunjukkan *di mana* halaman
resminya, dan Polaris tetap mengambil fakta dari halaman resmi itu.

---

## 1. Batas yang dipegang

| Peran | Boleh? | Alasannya |
|---|---|---|
| Agregator sebagai **petunjuk** letak halaman resmi | ya | itu memang fungsi tautannya |
| Agregator sebagai **source** yang di-crawl lalu diterbitkan | tidak | bukan penyelenggara; aturan official-source-first |
| Agregator sebagai **provider** | tidak | "Fully Scholarships" bukan pemberi beasiswa |
| Teks agregator (deadline, funding, ringkasan) masuk ke record | tidak | fakta harus dari halaman penyelenggara |
| Agregator menautkan agregator lain (rantai) | tidak | host sosial/agregator difilter |

Konsekuensi praktis: kalau halaman resmi tidak mencantumkan deadline, record itu
tetap **tanpa deadline** walaupun agregator menyebutkan tanggal. Pipeline tidak
meminjam klaim pihak ketiga.

---

## 2. Cara kerjanya

`scripts/harvest_aggregators.py`:

1. baca `sitemap` agregator (bukan halaman beranda) — fullyscholarships punya 771
   artikel, opportunitiescircle 1000+ per sitemap;
2. saring artikel yang judulnya memang soal award
   (`scholarship|fellowship|grant|award|funding|bursary|studentship`);
3. buka artikelnya, ambil tautan keluar;
4. buang tautan sosial, redirector, dan sesama agregator;
5. sisakan **URL domain resmi**, lalu daftarkan URL itu sebagai source —
   provider-nya domain itu sendiri, bukan agregatornya.

```bash
python scripts/harvest_aggregators.py --limit-articles 30            # lihat hasil
python scripts/harvest_aggregators.py --limit-articles 30 --register # jadi source
```

Negara source ditentukan dari suffix host (`.my`, `.de`, `.ac.uk`, …) plus daftar
host yang sudah dikenal (chevening.org → GB). URL yang negaranya tidak bisa
ditentukan **tidak** ditebak: dilaporkan sebagai `skipped`.

---

## 3. Hasil uji pertama

Satu putaran (`--limit-articles 30`):

- **52 source** terdaftar: GB 17, DE 12, JP 6, US 6, CN 4, AU 4, FR 2, KR 1
- 61 URL dilewati karena negaranya tidak bisa dipastikan dari host
- Contoh yang didapat: DAAD scholarship database, Chevening, Gates Cambridge,
  Rhodes House, Clarendon (Oxford), Swedish Institute, ETH Excellence, EPFL,
  Holland Scholarship, Stipendium Hungaricum, Fulbright, Yenching Academy

Crawl percobaan pada source radar GB (20 source, 55 halaman):

- 5 ekstraksi berhasil, **3 record** masuk katalog, 2 duplikat
- 13 record ditahan auto-review: 7 karena provider masih domain/batch label,
  5 karena nama masih judul halaman, 1 kurang field

Artinya radar ini **menambah sumber untuk crawl berulang**, bukan langsung
menambah puluhan record: tautan agregator kebanyakan menuju halaman *indeks*
(DAAD database, portal beasiswa), yang memang ditolak gate presisi sebagai
"bukan satu program".

Yang **tidak** terjadi: satu pun halaman fullyscholarships/opportunitiescircle
menjadi source, tidak ada provider bernama agregator, dan tidak ada deadline
yang dipinjam dari teks agregator.

Katalog setelah putaran ini: **142 approved** (dari 139), pending 13,
deadline 43, degree 107, funding 39.

---

## 4. Kenapa glornoscholarships.com dilewati

`https://glornoscholarships.com/robots.txt` menjawab **403** (Cloudflare), begitu
juga halaman berandanya. Situs yang menolak pembacaan otomatis tidak dipaksa;
kalau nanti terbuka, cukup tambahkan entri sitemap-nya ke `AGGREGATORS`.

---

## 5. Yang perlu dijaga ke depan

1. **Jangan menambah agregator sebagai provider** walau record-nya terlihat bagus.
2. **Jangan menyalin deadline agregator.** Kalau angka deadline naik tanpa crawl
   halaman resmi, berarti batas ini bocor.
3. **Rantai agregator**: kalau sebuah artikel hanya menautkan agregator lain,
   URL itu dibuang — radar tidak boleh berputar di antara pengumpul.
