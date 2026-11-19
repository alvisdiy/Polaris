# ADR-019 — The Legacy Data Condition, and What Was Done About It

- **Status:** Accepted (post-M10 Priority E)
- **Date:** 2026-10-04
- **Evidence:** `scripts/p10_legacy_triage.py` (read-only classification),
  `scripts/p10_legacy_reextract.py`, `scripts/p10_retire_orphans.py`

## Context

M10's integrity audit raised two findings and labelled both pre-existing:

- 17 records named `Unknown Scholarship`;
- 19 approved records with no approval action, no version rows and no
  provenance.

Both describe 2026-09-26, before the review service existed. Neither is
visible to a user: the 17 are unpublished, and the 19 carry real data.

## Group 1 — the 17 `Unknown Scholarship` records

M8's extractor stored the literal string `Unknown Scholarship` when it could
not find a name, which is a placeholder masquerading as an identity. Every one
of the 17:

- is `pending_review` — none was ever public, so nothing user-facing is
  wrong;
- has `provenance_origin = 'unknown'` and **zero** review actions;
- has a real `official_page_url`.

Reading those pages shows what M8 was actually looking at: pages that describe
no single scholarship.

| Page kind | Example |
|---|---|
| login redirect | `www2.naz.edu/auth/login?returnURL=…` |
| FAQ | `ntu.edu.sg/admissions/undergraduate/scholarships/faqs-on-scholarships` |
| programme index | `jsps.go.jp/j-grantsinaid/`, `daad.de/…/scholarships/` |
| fees overview | `u-tokyo.ac.jp/…/tuition_scholarships.html` |

### What Priority B changed about them

Re-running today's extractor over the same stored pages:

- **6 still produce no name.** The page genuinely does not name one
  scholarship.
- **11 now produce a name**, because the ranking and genericity rules improved.
  Two of those are genuinely right (`Scholarship for High School and Kosen
  Students`, `Studienstipendium (Uni und HAW)`); the rest are *overview
  headings* (`Access funding`, `Undergraduate fees and funding`) — better
  than a placeholder, but still not verified by a human.

### Decision

**Six records retired, eleven left pending.**

The six were retired through `ReviewService.reject()`, each with a written
reason naming what the page actually is. That path writes a review action and
a version row, so the retirement is auditable and reversible
(`REJECTED → PENDING_REVIEW` is a legal transition). Nothing was deleted and
`extraction_status` was never written directly.

The eleven stay in the queue. They are **un-curated, not corrupt**: today's
extractor can name them, and turning an extractor result into published data
requires a person reading the page. That is Priority H's work, done through
review rather than by migration.

## Group 2 — the 19 approved records with no review trail

All 19 were created in the same second (`2026-09-26 13:27:54`) by the legacy
bootstrap seed, and all share:

- `reviewed_by = NULL`, `review_notes = NULL`;
- **0** version rows, **0** review actions, no `field_provenance`.

They are not wrong. Each has a real name, a degree, a funding type and an
official URL:

```text
MEXT Scholarship for Research Students            Master        Fully Funded
DAAD Development-Related Postgraduate Courses    Master        Fully Funded
Chevening Scholarships                           Master        Fully Funded
DAAD Helmut-Schmidt-Programme                    Master        Fully Funded
MEXT Scholarship for Undergraduate Students       Bachelor      Fully Funded
…
```

### Decision: documented, not backfilled

**No migration, no backfill, no fabricated history.** Writing an approval row
for a review that never happened would be the single most damaging thing this
milestone could do to the audit trail: it would make the trail *look* complete
and be impossible to tell apart from a real one. Same for version rows and
provenance — a synthetic "version 1, approved by curator" is a forgery, not a
history.

The condition is instead recorded where it will be found:

- this ADR;
- `docs/v0.1/llm-extraction-contract.md` provenance section;
- the milestone report, as a named remaining risk.

The 20th approved record, `Polytechnic Foundation Programme (PFP)`, is the
contrast: 9 versions, 4 review actions, `reviewed_by = 'm91-curation'`, and
a `review_notes` that explains every decision including the ones that
deliberately left a field empty.

## Consequences

- `m10_integrity_audit.py` still reports 2 findings, both now explained in
  one place rather than annotated inline each run. The first count is 17
  because 11 of them are awaiting human curation, not because 17 are broken.
- The publication boundary is untouched: 0 of the 17 were ever public, and
  retiring the 6 changed nothing a user could see.
- A future milestone that wants these records published must acquire detail
  pages and review them. Backfilling the audit trail is not an option.

## Reproducing

```bash
PYTHONPATH=. python scripts/p10_legacy_triage.py      # classify both groups
PYTHONPATH=. python scripts/p10_legacy_reextract.py   # what today's extractor makes of them
PYTHONPATH=. python scripts/m10_integrity_audit.py    # 18 checks
```