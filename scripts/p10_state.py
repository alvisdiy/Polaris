"""Post-M10 §0 audit — dump the current state of the M10 pilot records.

Read-only. Prints what each pilot record actually holds today, with its
provenance, so Priority A reviews the real rows rather than the M10 report's
description of them.
"""

from __future__ import annotations

import json

from database.models.scholarship import Scholarship
from database.models.scholarship_review_action import ScholarshipReviewAction
from database.session import SessionLocal
from services.review.publication import is_published


def main() -> None:
    session = SessionLocal()
    try:
        rows = (
            session.query(Scholarship)
            .filter(Scholarship.provenance_origin == "exploration")
            .order_by(Scholarship.created_at.asc())
            .all()
        )
        print(f"pilot records (origin=exploration): {len(rows)}\n")
        for row in rows:
            print("=" * 100)
            print(f"id           : {row.scholarship_id}")
            print(f"name         : {row.scholarship_name}")
            print(f"status       : {row.extraction_status}  published={is_published(row)}")
            print(f"origin       : {row.provenance_origin}")
            print(f"official_url : {row.official_page_url}")
            print(f"application  : {row.application_url}")
            deadline = row.timeline.application_deadline if row.timeline else None
            print(f"deadline     : {deadline} state={row.deadline_state}")
            print(f"degree       : {row.degree}")
            print(f"funding      : {row.funding_type}")
            print(f"field        : {row.field_of_study}")
            print(f"provider     : {getattr(row.provider, 'provider_name', None)}")
            prov = row.field_provenance or {}
            print(f"unmapped_qual: {(prov.get('degree') or {}).get('unmapped_qualification')}")
            print(f"created_at   : {row.created_at}")
            print(f"field_prov   : {json.dumps(row.field_provenance, indent=2, default=str)}")
            actions = (
                session.query(ScholarshipReviewAction)
                .filter(ScholarshipReviewAction.scholarship_id == row.scholarship_id)
                .all()
            )
            print(f"actions      : {[(a.action, a.actor, a.reason) for a in actions]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
