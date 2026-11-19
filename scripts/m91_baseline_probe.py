"""M9.1 Phase 1 baseline DB snapshot. Read-only, no writes."""

from collections import Counter

from dotenv import load_dotenv
from sqlalchemy import func, select, text

from database.models import (
    RawDocument,
    Scholarship,
    ScholarshipReviewAction,
    ScholarshipVersion,
    SourceRegistry,
)
from database.session import SessionLocal

load_dotenv()


def main() -> None:
    session = SessionLocal()
    try:
        print("=== scholarships by extraction_status ===")
        rows = session.execute(
            select(Scholarship.extraction_status, func.count()).group_by(
                Scholarship.extraction_status
            )
        ).all()
        print(dict(rows) or "(empty)")

        print("\n=== sources by verification_state ===")
        rows = session.execute(
            select(SourceRegistry.verification_state, func.count()).group_by(
                SourceRegistry.verification_state
            )
        ).all()
        print(dict(rows) or "(empty)")

        print("\n=== sources by acquisition_state ===")
        rows = session.execute(
            select(SourceRegistry.acquisition_state, func.count()).group_by(
                SourceRegistry.acquisition_state
            )
        ).all()
        print(dict(rows) or "(empty)")

        print("\n=== scholarships by provenance_origin ===")
        rows = session.execute(
            select(Scholarship.provenance_origin, func.count()).group_by(
                Scholarship.provenance_origin
            )
        ).all()
        print(dict(rows) or "(empty)")

        print("\n=== NULL / audit gap counts ===")
        total = session.scalar(select(func.count()).select_from(Scholarship))
        print(f"total scholarships: {total}")
        for col in (
            "field_provenance",
            "quality_report",
            "extraction_confidence",
            "reviewed_at",
            "reviewed_by",
        ):
            n = session.scalar(
                select(func.count())
                .select_from(Scholarship)
                .where(getattr(Scholarship, col).is_(None))
            )
            print(f"  {col} IS NULL: {n}/{total}")

        approved_ids = session.execute(
            select(Scholarship.scholarship_id).where(
                Scholarship.extraction_status == "approved"
            )
        ).scalars().all()
        print(f"\napproved scholarships: {len(approved_ids)}")
        no_action = 0
        no_v1 = 0
        for sid in approved_ids:
            has_action = session.scalar(
                select(func.count())
                .select_from(ScholarshipReviewAction)
                .where(ScholarshipReviewAction.scholarship_id == sid)
            )
            if not has_action:
                no_action += 1
            has_v1 = session.scalar(
                select(func.count())
                .select_from(ScholarshipVersion)
                .where(
                    ScholarshipVersion.scholarship_id == sid,
                    ScholarshipVersion.version_number == 1,
                )
            )
            if not has_v1:
                no_v1 += 1
        print(f"  approved with NO review action: {no_action}")
        print(f"  approved with NO version 1:     {no_v1}")

        print("\n=== review action types recorded ===")
        rows = session.execute(
            select(
                ScholarshipReviewAction.action, func.count()
            ).group_by(ScholarshipReviewAction.action)
        ).all()
        print(dict(rows) or "(empty)")

        print("\n=== review actions total / orphan check ===")
        print("total review actions:", session.scalar(
            select(func.count()).select_from(ScholarshipReviewAction)
        ))
        print("orphan review actions (no scholarship):", session.scalar(
            select(func.count())
            .select_from(ScholarshipReviewAction)
            .where(ScholarshipReviewAction.scholarship_id.is_(None))
        ))

        print("\n=== identity / url hash duplicates ===")
        print("duplicate scholarship identity_key:", session.scalar(
            select(func.count()).select_from(
                select(Scholarship.identity_key)
                .where(Scholarship.identity_key.isnot(None))
                .group_by(Scholarship.identity_key)
                .having(func.count() > 1).subquery()
            )
        ))
        print("duplicate source official_url:", session.scalar(
            select(func.count()).select_from(
                select(SourceRegistry.official_url)
                .group_by(SourceRegistry.official_url)
                .having(func.count() > 1).subquery()
            )
        ))
        print("duplicate url_hash:", session.scalar(
            select(func.count()).select_from(
                select(SourceRegistry.url_hash)
                .where(SourceRegistry.url_hash.isnot(None))
                .group_by(SourceRegistry.url_hash)
                .having(func.count() > 1).subquery()
            )
        ))
        print("NULL url_hash:", session.scalar(
            select(func.count())
            .select_from(SourceRegistry)
            .where(SourceRegistry.url_hash.is_(None))
        ))

        print("\n=== pg_indexes on scholarship_version ===")
        rows = session.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename='scholarship_version'"
        )).all()
        for name, definition in rows:
            print(f"  {name}: {definition}")
        print("unique constraints on scholarship_version:")
        cons = session.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='scholarship_version'::regclass"
        )).all()
        for name, definition in cons:
            print(f"  {name}: {definition}")

        print("\n=== degree values stored ===")
        rows = session.execute(
            select(Scholarship.degree, func.count()).group_by(Scholarship.degree)
        ).all()
        print(Counter({str(d): c for d, c in rows}).most_common())

        print("\n=== CHECK constraints on scholarship.degree ===")
        rows = session.execute(text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid='scholarship'::regclass AND contype='c'"
        )).all()
        for name, definition in rows:
            print(f"  {name}: {definition}")
        if not rows:
            print("  (none)")

        print("\n=== raw documents ===")
        print("total raw documents:", session.scalar(
            select(func.count()).select_from(RawDocument)
        ))
    finally:
        session.rollback()
        session.close()


if __name__ == "__main__":
    main()
