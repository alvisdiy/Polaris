"""M9.1 Phase 8 — read-only audit of approved records and their history.

Measures what Phase 8 was asked to measure, without changing anything:

    approved with / without a review action
    approved with / without a version row
    approved with / without field provenance
    approved with / without a source or provider

The point is to see which records were published by the legacy bootstrap paths
and which went through review. Nothing here rewrites history: an approved
record with no review action is a true statement about how it was published,
and back-filling a reviewer to hide that would be a lie in the audit trail.

Also re-checks the two invariants that matter most, on live data:
  * no duplicate version numbers per scholarship
  * every non-approved record is invisible to the public read path
"""

from __future__ import annotations

from dotenv import load_dotenv
from sqlalchemy import func, select

from database.models import (
    Scholarship,
    ScholarshipCandidateRevision,
    ScholarshipReviewAction,
    ScholarshipVersion,
)
from database.session import SessionLocal
from services.domain.vocabulary import DEGREE
from services.review.publication import published_filter
from services.scholarship.repository import ScholarshipRepository


def main() -> None:
    load_dotenv()
    session = SessionLocal()
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, note: str = "") -> None:
        checks.append((name, bool(condition), note))
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f"  ({note})" if note else ""))

    try:
        approved = (
            session.query(Scholarship)
            .filter(published_filter())
            .all()
        )
        ids = [s.scholarship_id for s in approved]

        with_action = {
            sid
            for (sid,) in session.query(ScholarshipReviewAction.scholarship_id)
            .filter(ScholarshipReviewAction.scholarship_id.in_(ids))
            .distinct()
            .all()
        } if ids else set()
        with_version = {
            sid
            for (sid,) in session.query(ScholarshipVersion.scholarship_id)
            .filter(ScholarshipVersion.scholarship_id.in_(ids))
            .distinct()
            .all()
        } if ids else set()
        with_provenance = {s.scholarship_id for s in approved if s.field_provenance}

        print("=" * 78)
        print("M9.1 PHASE 8 — APPROVED RECORD AUDIT (read-only)")
        print("=" * 78)
        print(
            "\nscholarships total            : "
            f"{session.scalar(select(func.count()).select_from(Scholarship))}"
        )
        for status, count in session.query(
            Scholarship.extraction_status, func.count()
        ).group_by(Scholarship.extraction_status).all():
            print(f"  {status:<24}: {count}")
        print(f"\napproved records              : {len(approved)}")
        print(f"  with a review action        : {len(with_action)}")
        print(
            f"  without a review action     : {len(ids) - len(with_action)}"
            "  (legacy bootstrap)"
        )
        print(f"  with a version row          : {len(with_version)}")
        print(
            f"  without a version row       : {len(ids) - len(with_version)}"
            "  (legacy bootstrap)"
        )
        print(f"  with field provenance       : {len(with_provenance)}")
        print(f"  without field provenance    : {len(ids) - len(with_provenance)}")
        print(f"  without a provider link     : {sum(1 for s in approved if s.provider_id is None)}")
        print(
            "\ncandidate revisions           : "
            f"{session.scalar(select(func.count()).select_from(ScholarshipCandidateRevision))}"
        )
        print(f"version rows                  : {session.scalar(select(func.count()).select_from(ScholarshipVersion))}")
        print(
            "review actions               : "
            f"{session.scalar(select(func.count()).select_from(ScholarshipReviewAction))}"
        )

        # --- integrity invariants on live data --------------------------
        print("\n[1] Version integrity")
        duplicates = (
            session.query(
                ScholarshipVersion.scholarship_id,
                ScholarshipVersion.version_number,
                func.count(),
            )
            .group_by(ScholarshipVersion.scholarship_id, ScholarshipVersion.version_number)
            .having(func.count() > 1)
            .all()
        )
        check("no duplicate (scholarship, version_number)", not duplicates, str(duplicates[:3]))

        # --- publication invariants -------------------------------------
        print("\n[2] Publication integrity")
        unpublished = (
            session.query(Scholarship)
            .filter(Scholarship.extraction_status != "approved")
            .all()
        )
        repo = ScholarshipRepository(session)
        leaked = [
            str(s.scholarship_id)
            for s in unpublished
            if repo.get_published_by_id(s.scholarship_id) is not None
        ]
        check("no unpublished record is publicly readable", not leaked, str(leaked[:3]))

        out_of_vocab = [
            str(s.scholarship_id)
            for s in session.query(Scholarship)
            .filter(Scholarship.degree.isnot(None))
            .all()
            if not DEGREE.is_valid(s.degree)
        ]
        check("no published degree outside the vocabulary", not out_of_vocab, str(out_of_vocab[:3]))

        print("\n" + "=" * 78)
        passed = sum(1 for _, ok, _ in checks if ok)
        print(f"RESULT: {passed}/{len(checks)} checks passed")
        failed = [name for name, ok, _ in checks if not ok]
        if failed:
            print("FAILED:", ", ".join(failed))
        print("=" * 78)
        if failed:
            raise SystemExit(1)
    finally:
        session.rollback()
        session.close()


if __name__ == "__main__":
    main()
