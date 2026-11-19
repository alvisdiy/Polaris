# Review Queue CLI — 10 November 2026

**Tujuan:** memberi operator satu jalan untuk mengosongkan antrean `pending_review` tanpa melewati batas publikasi.
**Status:** implemented + tested against the development database (read-only run) and a rollback-isolated test database.

---

## 1. Masalah

Antrean 60 record berumur 15–36 hari, sementara approval rate 20,7% (41 approved / 198 decided). `ReviewService` sudah punya state machine, quality gate, version row, dan audit action — yang tidak ada adalah cara menjalankannya tanpa menulis kode Python atau memanggil API satu per satu.

---

## 2. Yang dibangun

`scripts/review_queue.py`:

| Command | Fungsi |
|---|---|
| `summary` | Total, pending, approved, rejected, approval rate, origin, umur pending tertua |
| `list` | Daftar record dengan id, nama, provider, negara, confidence, gate yang memblokir |
| `approve <id> --yes` | Publish lewat `ReviewService.approve` |
| `reject <id> --yes` | Tolak lewat `ReviewService.reject` (alasan wajib) |

Keamanan:

- **Tidak menulis `extraction_status` langsung.** Semua keputusan lewat `ReviewService`, sehingga version row + audit action tetap ditulis bersama.
- **`--yes` wajib** untuk approve/reject. Salah ketik id tidak bisa mempublikasikan record.
- **Alasan wajib** untuk reject; approve boleh dengan alasan yang dicatat.
- **`--override`** hanya untuk field yang memang overridable (degree, funding, field, deadline, GPA), dan tetap tercatat.
- `--actor` disimpan di audit action (default `POLARIS_REVIEWER` atau `cli`).

---

## 3. Bukti

Dijalankan pada database development (read-only):

```text
CURATION SUMMARY
Total:               259
Pending review:      60
Approved:            41
Rejected:            157
Approval rate:       0.2071
By origin:           {'unknown': 153, 'exploration': 79, 'phase3_acquisition': 26}
Oldest pending:      2026-10-04T16:45:01

PENDING REVIEW — 60 record(s)
ID        NAME                                  PROVIDER          COUNTRY   CONF  GATES
3f916222  Ernst Mach Grant – ASEA-UNINET...    ITS Global Eng... Indonesia 1.00  degree
028d57cf  Dr Mai Yamani Scholarship             SOAS              UK        0.57  none
...
```

Test: 7 integration tests (`tests/integration/test_review_queue_cli.py`) — list, JSON, summary, refuse-without-yes, approve + audit, reject + audit, reject-requires-reason.

---

## 4. Cara pakai

```bash
python scripts/review_queue.py summary
python scripts/review_queue.py list --country GB --limit 20
python scripts/review_queue.py approve <id> --actor alice --reason "verified" --yes
python scripts/review_queue.py reject <id> --actor alice --reason "index page" --yes
```

Untuk record yang gate-nya bisa di-override:

```bash
python scripts/review_queue.py approve <id> --actor alice \
  --reason "degree read from the programme page" --override --yes
```

---

## 5. Yang belum

- **UI review.** CLI cukup untuk satu operator; reviewer non-teknis butuh tampilan.
- **Bulk triage.** Saat ini satu id per keputusan.
- **Identitas reviewer.** `--actor` adalah klaim, bukan autentikasi; token admin hanya mengautentikasi permukaan API.
- **Mengosongkan 60 record** adalah pekerjaan kurasi, bukan pekerjaan kode. CLI-nya sudah siap; keputusannya butuh manusia yang membaca halaman sumber.
