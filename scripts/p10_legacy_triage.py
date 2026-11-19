"""Post-M10 Priority E — triage the two legacy groups M10 flagged.

Read-only. Classifies rather than changes anything:

  * the "Unknown Scholarship" records, which have no usable identity;
  * the approved records with no approval action, which predate the review
    service.

The point is to decide what each group *is*, not to clean it up. Nothing here
writes: retiring a record or backfilling history both need a decision that
§12 of the milestone reserves, and this script exists to give that decision
its evidence.
"""

from __future__ import annotations

from sqlalchemy import text

from database.session import SessionLocal

UNKNOWN_SQL = """
SELECT s.scholarship_id, s.scholarship_name, s.extraction_status,
       s.official_page_url, s.created_at, s.provenance_origin,
       p.provider_name, c.name AS country,
       (SELECT count(*) FROM scholarship_version v
         WHERE v.scholarship_id = s.scholarship_id) AS versions,
       (SELECT count(*) FROM scholarship_review_action a
         WHERE a.scholarship_id = s.scholarship_id) AS actions
FROM scholarship s
JOIN provider p ON p.provider_id = s.provider_id
JOIN country c ON c.country_id = s.country_id
WHERE s.scholarship_name ILIKE 'unknown%'
ORDER BY s.created_at
"""

UNAPPROVED_LEGACY_SQL = """
SELECT s.scholarship_id, s.scholarship_name, s.degree, s.funding_type,
       s.official_page_url, s.created_at, s.reviewed_by, s.review_notes,
       p.provider_name, c.name AS country,
       (SELECT count(*) FROM scholarship_version v
         WHERE v.scholarship_id = s.scholarship_id) AS versions,
       (SELECT count(*) FROM scholarship_review_action a
         WHERE a.scholarship_id = s.scholarship_id) AS actions
FROM scholarship s
JOIN provider p ON p.provider_id = s.provider_id
JOIN country c ON c.country_id = s.country_id
WHERE s.extraction_status = 'approved'
  AND NOT EXISTS (
      SELECT 1 FROM scholarship_review_action a
      WHERE a.scholarship_id = s.scholarship_id AND a.action = 'approved'
  )
ORDER BY s.created_at
"""


def main() -> None:
    session = SessionLocal()
    try:
        print("=" * 100)
        print("GROUP 1 — records with no usable identity")
        print("=" * 100)
        rows = session.execute(text(UNKNOWN_SQL)).fetchall()
        print(f"count: {len(rows)}\n")
        for r in rows:
            print(f"{r.scholarship_id}  {r.extraction_status}  origin={r.provenance_origin}")
            print(f"  name     : {r.scholarship_name!r}")
            print(f"  url      : {r.official_page_url}")
            print(f"  provider : {r.provider_name}   country: {r.country}")
            print(f"  created  : {r.created_at}")
            print(f"  versions : {r.versions}   review actions: {r.actions}")
            print()

        print("=" * 100)
        print("GROUP 2 — approved records with no approval action")
        print("=" * 100)
        rows = session.execute(text(UNAPPROVED_LEGACY_SQL)).fetchall()
        print(f"count: {len(rows)}\n")
        for r in rows:
            print(f"{r.scholarship_id}  {r.scholarship_name}")
            print(f"  degree   : {r.degree}   funding: {r.funding_type}")
            print(f"  provider : {r.provider_name}   country: {r.country}")
            print(f"  url      : {r.official_page_url}")
            print(f"  created  : {r.created_at}")
            print(f"  reviewed : by={r.reviewed_by!r} notes={r.review_notes!r}")
            print(f"  versions : {r.versions}   review actions: {r.actions}")
            print()

        print("=" * 100)
        print("GROUP 2 — the record that DOES have a review trail, for contrast")
        print("=" * 100)
        rows = session.execute(
            text(
                """
                SELECT s.scholarship_name, s.reviewed_by, s.review_notes,
                       (SELECT count(*) FROM scholarship_version v
                         WHERE v.scholarship_id = s.scholarship_id) AS versions,
                       (SELECT count(*) FROM scholarship_review_action a
                         WHERE a.scholarship_id = s.scholarship_id) AS actions
                FROM scholarship s
                WHERE s.extraction_status = 'approved'
                  AND EXISTS (
                      SELECT 1 FROM scholarship_review_action a
                      WHERE a.scholarship_id = s.scholarship_id
                        AND a.action = 'approved'
                  )
                """
            )
        ).fetchall()
        for r in rows:
            print(f"{r.scholarship_name}")
            print(f"  reviewed : by={r.reviewed_by!r}")
            print(f"  notes    : {r.review_notes!r}")
            print(f"  versions : {r.versions}   review actions: {r.actions}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
