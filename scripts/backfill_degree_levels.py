"""Backfill scholarship_degree_level from the raw document already stored.

The multi-level detector was added after these records were extracted, so their
pages were fetched and kept, but the set of levels was discarded. Re-crawling
every source to recover one field would spend the crawl budget on pages Polaris
already has; the raw HTML is in ``raw_document`` keyed by the document id in
``scholarship.field_provenance``.

Only pending records are touched by default. A published record's fields are a
review decision, and rewriting them from a heuristic would change what a
reviewer approved without anyone looking. Pass ``--include-decided`` to widen it
deliberately.

    python scripts/backfill_degree_levels.py --dry-run
    python scripts/backfill_degree_levels.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from database.models.raw_document import RawDocument  # noqa: E402
from database.models.scholarship import Scholarship  # noqa: E402
from database.models.scholarship_degree_level import (  # noqa: E402
    ScholarshipDegreeLevel,
)
from services.domain.degree_levels import declared_award_levels  # noqa: E402
from services.ingestion.cleaner import strip_invisible_content  # noqa: E402


def _text_of(html: str) -> str:
    """Visible text of a stored document.

    Tabs and cell boundaries matter here: the label and its values sit in
    adjacent table cells, and a renderer that drops the separator would join
    "Academic level" to the first level and hide the block's shape.
    """
    visible, _ = strip_invisible_content(html)
    try:
        import trafilatura

        text = trafilatura.extract(
            visible, include_comments=False, include_tables=True, no_fallback=False
        )
        if text:
            return text
    except Exception:  # trafilatura missing or refusing this page
        pass
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(visible, "html.parser")
    return soup.get_text("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-decided", action="store_true")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)

    from database.session import SessionLocal

    session = SessionLocal()
    try:
        query = select(Scholarship).where(Scholarship.degree.is_(None))
        if not args.include_decided:
            query = query.where(Scholarship.extraction_status == "pending_review")
        rows = session.scalars(query.limit(args.limit)).all()

        scanned = written = 0
        for scholarship in rows:
            provenance = scholarship.field_provenance or {}
            document_id = None
            for entry in provenance.values():
                if isinstance(entry, dict) and entry.get("document_id"):
                    document_id = entry["document_id"]
                    break
            if not document_id:
                continue
            document = session.get(RawDocument, document_id)
            if document is None or not document.raw_content:
                continue
            scanned += 1
            levels = declared_award_levels(_text_of(document.raw_content))
            if not levels:
                continue
            written += 1
            print(f"{scholarship.scholarship_id} {scholarship.scholarship_name[:60]!r} -> {levels}")
            if args.dry_run:
                continue
            existing = {row.degree for row in (scholarship.degree_levels or [])}
            for level in levels:
                if level not in existing:
                    scholarship.degree_levels.append(ScholarshipDegreeLevel(degree=level))
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
        print(f"\nscanned={scanned} with_levels={written} dry_run={args.dry_run}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
