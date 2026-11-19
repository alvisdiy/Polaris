"""M9.1 Phase 1 — reproduce the CRITICAL publication-bypass finding.

Runs `_merge_reacquisition` against the live APPROVED Singapore record inside a
transaction that is ALWAYS rolled back. Nothing is committed.
"""

from __future__ import annotations

from datetime import date

from dotenv import load_dotenv
from sqlalchemy import func, select

from database.models import (
    Scholarship,
    ScholarshipReviewAction,
    ScholarshipTimeline,
    ScholarshipVersion,
)
from database.session import SessionLocal
from services.exploration.acquisition_service import AcquisitionService
from services.review.publication import is_published

TARGET = "e2a5bfd4-2636-4869-90fa-dcd0f75d1a8a"  # approved SG exploration record


def snapshot(session, sid):
    s = session.get(Scholarship, sid)
    session.refresh(s)
    tl = session.execute(
        select(ScholarshipTimeline).where(ScholarshipTimeline.scholarship_id == sid)
    ).scalar_one_or_none()
    versions = session.scalar(
        select(func.count())
        .select_from(ScholarshipVersion)
        .where(ScholarshipVersion.scholarship_id == sid)
    )
    actions = session.scalar(
        select(func.count())
        .select_from(ScholarshipReviewAction)
        .where(ScholarshipReviewAction.scholarship_id == sid)
    )
    last_version = session.scalar(
        select(func.max(ScholarshipVersion.version_number)).where(
            ScholarshipVersion.scholarship_id == sid
        )
    )
    return {
        "name": s.scholarship_name,
        "status": s.extraction_status,
        "published": is_published(s),
        "deadline": (tl.application_deadline.isoformat() if tl and tl.application_deadline else None),
        "cycle": (tl.application_cycle if tl else None),
        "deadline_state": s.deadline_state,
        "last_verified_at": s.last_verified_at.isoformat() if s.last_verified_at else None,
        "versions": versions,
        "last_version_number": last_version,
        "review_actions": actions,
        "field_provenance": s.field_provenance,
    }


def main() -> None:
    load_dotenv()
    session = SessionLocal()
    try:
        before = snapshot(session, TARGET)
        print("=== BEFORE (live approved record) ===")
        for k, v in before.items():
            print(f"  {k}: {v}")

        assert before["status"] == "approved", "target record is not approved"
        assert before["published"] is True, "target record is not published"

        # Build a "fresh" incoming extraction with a new deadline, exactly the
        # shape _persist_with_dedup would hand to _merge_reacquisition.
        existing = session.get(Scholarship, TARGET)
        service = AcquisitionService(session)
        fresh = Scholarship(
            scholarship_name=existing.scholarship_name,
            degree=None,  # not copied: the live record's legacy degree is out-of-vocabulary
            funding_type=existing.funding_type,
            official_page_url=existing.official_page_url,
            provider_id=existing.provider_id,
            country_id=existing.country_id,
            source_id=existing.source_id,
        )
        fresh.timeline = ScholarshipTimeline(
            application_deadline=date(2099, 1, 1),
            application_cycle="2099-cycle",
        )
        session.add(fresh)
        session.flush()

        print("\n=== invoking AcquisitionService._merge_reacquisition ===")
        service._merge_reacquisition(existing, fresh, "Synthetic reacquisition probe text.")
        session.flush()

        after = snapshot(session, TARGET)
        print("\n=== AFTER (in-transaction, NOT committed) ===")
        for k, v in after.items():
            print(f"  {k}: {v}")

        print("\n=== DIFF ===")
        for key in before:
            if before[key] != after[key]:
                print(f"  MUTATED {key}: {before[key]!r} -> {after[key]!r}")

        violations = [
            k for k in ("deadline", "cycle", "deadline_state", "last_verified_at")
            if before[k] != after[k]
        ]
        print("\n=== VERDICT ===")
        print(f"  status still 'approved': {after['status'] == 'approved'}")
        print(f"  published still True:    {after['published'] is True}")
        print(f"  review actions changed:  {before['review_actions'] != after['review_actions']}")
        print(f"  version bumped silently: {before['versions'] != after['versions']}")
        if violations and after["status"] == "approved" and before["review_actions"] == after["review_actions"]:
            print("  >>> CRITICAL CONFIRMED: published fields mutated with no review event.")
        else:
            print("  >>> NOT REPRODUCED")
    finally:
        session.rollback()
        session.close()
        print("\n[transaction rolled back - nothing persisted]")


if __name__ == "__main__":
    main()
