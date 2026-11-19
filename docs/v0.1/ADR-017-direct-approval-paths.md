# ADR-017 — The Publication State Has Exactly One Writer

- **Status:** Accepted (M9.1 Phase 8)
- **Date:** 2026-10-03
- **Related:** ADR-015 (domain model), ADR-016 (degree vocabulary), ADR-017 guard test

## Context

`ReviewService` is supposed to own `extraction_status`: it writes the new
status, a `ScholarshipReviewAction` and a `ScholarshipVersion` in one
transaction, so a publication is always attributable.

Phase 8 inventoried every write to that column in the repository. Two paths
wrote `"approved"` outside the state machine:

| Path | Class | Behaviour |
|---|---|---|
| `scripts/run_mext_pipeline.py` | production acquisition | auto-approved every extracted record ("Auto-approve for MVP, no human review UI yet") |
| `scripts/seed_manual_scholarships.py` | bootstrap seed | wrote `approved` with the comment "Manually verified -> Approved" |

The first was a genuine bypass: crawler → extractor → **published**, with no
reviewer, no version row and no audit action. A page that said anything
parseable became a public record.

The second is different in kind. It seeds a hand-curated catalogue that a human
verified outside the system. That verification is a historical fact, but it
never happened *through* the review workflow, so recording it as a review would
mean inventing a reviewer and an evidence URL.

## Decision

**`ReviewService` is the only writer of the published state. Every other path
queues for review.**

- `run_mext_pipeline` persists to `PENDING_REVIEW` and stops. Approving is a
  separate, human step through the review API or `ReviewService.approve()`.
- `seed_manual_scholarships` creates records in `PENDING_REVIEW` by default.
  `--approve-directly` exists only to rebuild the legacy bootstrap state of an
  old development database; it writes the status and nothing else — deliberately
  **not** a synthetic review action, reviewer or timestamp.

**Legacy approved records are not rewritten.** 19 of the 20 approved records in
the development database predate the review workflow and have no review action,
no version row and no provenance. That is a true statement about how they were
published. Manufacturing a reviewer to hide it would make the audit trail lie,
which is worse than an incomplete one.

## Enforcement

`tests/integration/test_direct_approval_guard.py` parses every module under
`services/`, `scripts/` and `database/migrations/` and fails if any of them
assigns `extraction_status = "approved"`, including through `dict(...)`,
`.update(...)` or a raw SQL `SET`. Exceptions are listed explicitly with a
reason, so the next direct approval is a deliberate edit to a reviewed file
rather than a line that slips in with a feature.

The same file proves the boundary behaviourally: a mapped extraction is in
`PENDING_REVIEW`, is invisible to the public read path, and becomes visible
only after `ReviewService.approve()`.

## Consequences

- The MEXT pipeline script no longer publishes. Running it leaves a review
  queue to work through — which is the point.
- Bootstrap data is reproducible without pretending it was reviewed.
- The 19 legacy records remain publicly visible with no provenance. If a
  production deployment ever inherits that data, the honest options are to
  re-verify them through review or to mark them as bootstrap; inventing history
  is not one of them.