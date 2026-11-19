# Frontend Redesign — 16 November 2026

Redesign seluruh permukaan aplikasi (8 halaman + 18 komponen), memakai arah
visual "arsip riset" dan satu aksen Three.js untuk hero.

---

## 1. Arah desain

**The Ledger** — antarmuka terbaca seperti arsip riset, bukan dashboard startup:

| Elemen | Keputusan |
|---|---|
| Kertas | #F3EDDF, permukaan #FBF7EC — hangat, bukan putih |
| Tinta | #1A1512 (bukan hitam murni), sekunder #5B5145 |
| Aksen | Vermilion #B8402A — satu saja, untuk aksi dan angka kunci |
| Bukti | Moss #2C5347 untuk semantik "verified" |
| Display | Fraunces (serif modern, optical sizing) |
| Body | Instrument Sans |
| Metadata | IBM Plex Mono, uppercase 0.1em — semua fakta mesin |
| Garis | Hairline 1px, 2px untuk struktur |

Alasan: produk ini menjual **ketertelusuran**. Desain harus membuat sumber,
status deadline, dan field yang tidak diketahui terlihat — bukan menyembunyikannya.

---

## 2. Yang berubah

| Berkas | Perubahan |
|---|---|
| `styles/tokens.css` | token baru: warna, tipografi 3 keluarga, radius nyaris kotak, shadow kartu |
| `styles/base.css` | skala tipografi editorial, grain kertas, link, fokus, tombol bersama, animasi `rise` |
| `index.html` | font Fraunces + Instrument Sans + IBM Plex Mono, theme-color |
| `NavBar`, `FooterBar` | wordmark serif, nav mono uppercase dengan garis aktif vermilion, footer 3 kolom |
| `ScholarshipCard` | slip kertas: garis atas 2px, hover lift, chip metadata mono, panah pada "View details" |
| `DeadlineBadge`, `FilterChip`, `SaveButton`, `CompareToggle`, `SourceCitation` | mono + hairline, status warna tetap disertai kata & ikon |
| `EmptyState`, `ErrorState`, `SkeletonBlock`, `ProgressLine` | bingkai hairline, judul serif, shimmer transform-only |
| `HomeView` | hero 2 kolom dengan eyebrow, 3 langkah bergaris (bukan kartu), globe 3D |
| `DiscoverView` | rail filter sticky 17rem + kolom hasil, kartu daftar |
| `ScholarshipDetailView` | judul serif besar, baris fakta berlabel mono, rail aksi kanan |
| `MatchView`, `CompareView`, `SavedView`, `AboutView`, `NotFoundView` | token yang sama, tabel/daftar bergaris |
| `ProfileForm`, `ExplanationPanel`, `ScoreBadge`, `GlobalSearch`, `ThemeToggle`, `MobileMenuSheet` | diselaraskan ke sistem |

---

## 3. ThreeUI: apa yang dipakai dan kenapa tidak semuanya

`threeui.com` adalah library **Three.js / WebGL** — landing page, hero, shader,
background 3D, tombol shader. Bukan UI kit untuk aplikasi data.

Yang dipakai: **satu aksen globe wireframe** di hero (`components/HeroGlobe.vue`),
karena:
- produk ini butuh kecepatan dan keterbacaan; 3D di seluruh UI akan mengalahkan
  keduanya;
- item yang benar-benar "ThreeUI" kebanyakan PRO (berbayar) dan berupa halaman
  penuh, bukan komponen;
- globe adalah metafora yang tepat: beasiswa lintas negara.

Aturan yang dipasang:
- kolom sendiri — tidak pernah menimpa teks;
- `aria-hidden`, tanpa pointer events, tanpa data;
- dilewati di bawah 900px dan saat `prefers-reduced-motion`;
- `three` diimpor dinamis (chunk terpisah 753 KB, tidak masuk bundle awal);
- warna diambil dari token (ink + vermilion), jadi dark mode ikut tanpa palet baru.

Catatan: MCP Stitch tetap membalas **401** di environment ini, jadi `DESIGN.md`
disiapkan di `docs/design/DESIGN.md` agar bisa langsung di-upload ke Stitch saat
token-nya sudah aktif.

---

## 4. Perbaikan fungsional yang ikut masuk

1. **Filter negara** kini memuat Malaysia dan Brunei (sebelumnya hardcode 10
   negara, sehingga record MY/BN tidak bisa difilter).
2. **`degree_levels` ditampilkan**: kartu menampilkan set level (mis.
   `Master · PhD`), dan detail menampilkan "Level not stated on the page" bila
   kosong — bukan baris kosong.
3. **Funding kosong** ditulis eksplisit: "Funding not stated on the page".
4. **Ligatur dekoratif Fraunces dimatikan** pada heading; `ffi` di "official"
   terbaca seperti glitch di ukuran display.
5. **Tidak ada teks yang tertimpa globe** — hero memakai grid area, bukan
   absolute overlay.

---

## 5. Verifikasi

- `npm run build` sukses (three.js sebagai chunk async terpisah).
- Screenshot 1440×1000: `docs/design/screenshots/{home,discover,detail,match,about}.png`.
- Hero: globe di kolom kanan, teks bersih, tombol primer ink / sekunder outline.
- Discover: 140 record, rail filter sticky, kartu bergaris atas ink.
- Detail: fakta berlabel mono, status "not stated" muncul untuk funding kosong.
- Mobile 426px: nav menyusut ke menu, globe disembunyikan, kartu satu kolom.

---

## 6. Data saat ini (setelah pipeline DE/JP/US)

| Metrik | Nilai |
|---|---:|
| Approved | 145 |
| Pending | 19 |
| Punya deadline | 44 |
| Punya degree | 109 |
| Punya funding | 41 |

Pipeline radar terakhir: DE 28 halaman → 1 record, JP 50 → 4, US 26 → 4.
