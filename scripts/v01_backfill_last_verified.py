"""Phase 7 — backfill ``last_verified_at`` from what was actually recorded.

The field answers "when did someone last check this record against its
source?", and Phase 7 found it empty on records that had just been corrected
against a live official page. Two causes, one of them now fixed in the review
service:

* ``correct()`` never set it, even with an ``evidence_url`` — fixed there;
* every record corrected before that fix still shows nothing.

The backfill reads the audit trail rather than guessing. A review action that
carries an ``evidence_url`` is, by construction, a moment when someone
attested something against a page — an approval against a source, a
correction citing evidence, an accepted candidate whose source URL was
re-checked. The most recent such action's ``occurred_at`` is when the record
was last verified, so that is what gets written.

Two things it deliberately does not do:

* it does not invent a timestamp for a record with no such action — those stay
  NULL, which is the honest answer;
* it does not touch ``reviewed_at``. Re-verification and curation are separate
  facts and Phase 4's test depends on them staying separate.

    python scripts/v01_backfill_last_verified.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.session import SessionLocal  # noqa: E402

# Only actions that mean "someone checked this against a page". A rejection
# and a submission are not verification: neither asserts the record matches
# its source.
VERIFIERS = ("approved", "corrected", "candidate_approved")

SQL = """
SELECT s.scholarship_id, s.scholarship_name, s.last_verified_at,
       max(a.occurred_at) AS verified_at,
       (array_agg(a.action ORDER BY a.occurred_at DESC))[1] AS action,
       count(*) AS n
FROM scholarship s
JOIN scholarship_review_action a ON a.scholarship_id = s.scholarship_id
WHERE a.evidence_url IS NOT NULL
  AND a.action = ANY(:verifiers)
GROUP BY s.scholarship_id, s.scholarship_name, s.last_verified_at
HAVING s.last_verified_at IS NULL
    OR s.last_verified_at < max(a.occurred_at)
ORDER BY 3 NULLS FIRST, s.scholarship_name
"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from sqlalchemy import text

    session = SessionLocal()
    try:
        rows = session.execute(text(SQL), {"verifiers": list(VERIFIERS)}).mappings().all()
        print(f"records whose last_verified_at can be advanced: {len(rows)}\n")

        for row in rows:
            current = row["last_verified_at"]
            marker = "NULL" if current is None else current.isoformat()
            print(
                f"  {row['scholarship_name'][:56]:58} {marker:>26} -> "
                f"{row['verified_at'].isoformat()}  ({row['action']}, n={row['n']})"
            )
            if args.dry_run:
                continue
            session.execute(
                text(
                    "UPDATE scholarship SET last_verified_at = :v, updated_at = now() "
                    "WHERE scholarship_id = :c"
                ),
                {"v": row["verified_at"], "c": row["scholarship_id"]},
            )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
            print(f"\nwrote {len(rows)} rows")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
