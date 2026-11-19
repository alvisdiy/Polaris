"""Phase 3 follow-up — two records the quality gate let through that it should not.

The gate did its job on seven records in `v01_apply_phase3_rejections.py`, which
stayed in review blocked on ``degree``. These two passed the gate outright and
were approved by the Phase 3 run, so they are being withdrawn here.

Both are aggregator or marketing pages, not scholarship pages:

* "970,000 registrants" came from prospects.ac.uk/postgraduate-recruiters, a
  recruitment advertising sales page. The extractor's best heading was the
  metric in the middle of its copy, and the name is that number.
* "PM Yasasvi Post-Matric Scholarship for OBC Students" came from
  wemakescholars.com/post-doc-scholarships-for-international-students, a
  listing titled "190+ Post Doc scholarships 2026-27" — the same aggregator
  category-page shape as the other six.

The reason both reached publication is worth recording rather than hiding:
the gate checks that a record has a name, a provider, a country and an
official URL. It does not check that the name *is a scholarship name*, because
that question needs a judgement about the page's purpose, not a field
comparison. Phase 3 read the gate's pass as sufficient. It was not.

The jobs.ac.uk studentships and the individual sheffield.ac.uk pages in the
same batch are real pages for real awards and stay approved.

    python scripts/v01_apply_phase3b_rejections.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.models.scholarship_review_action import ReviewSource  # noqa: E402
from database.session import SessionLocal  # noqa: E402

ACTOR = "phase3-review"

REJECTIONS = [
    (
        "970,000 registrants",
        "https://www.prospects.ac.uk/postgraduate-recruiters",
        "the source is a recruitment advertising sales page, not a scholarship. "
        "The extracted name is a marketing metric from its copy ('Tailored "
        "email targeting from a pool of 970,000 registrants'). There is no "
        "award on this page to correct the record into",
    ),
    (
        "PM Yasasvi Post-Matric Scholarship for OBC Students",
        "https://www.wemakescholars.com/post-doc-scholarships-for-international-students",
        "the source is an aggregator listing page titled '190+ Post Doc "
        "scholarships 2026-27', not a page for this award. The page links to "
        "it rather than stating its terms, and 'Post-Matric' is a school-level "
        "qualification with no level in the degree vocabulary",
    ),
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from sqlalchemy import select

    from database.models.scholarship import Scholarship
    from services.review.service import ReviewService

    session = SessionLocal()
    try:
        service = ReviewService(session)
        for name, url, reason in REJECTIONS:
            record = session.execute(
                select(Scholarship).where(Scholarship.scholarship_name == name)
            ).scalar_one_or_none()
            if record is None:
                print(f"MISSING  {name}")
                continue
            if record.extraction_status == "rejected":
                print(f"ALREADY REJECTED  {name}")
                continue
            print(f"REJECT   {name}")
            if args.dry_run:
                continue
            outcome = service.reject(
                str(record.scholarship_id),
                actor=ACTOR,
                reason=reason,
                source=ReviewSource.SYSTEM,
                evidence_url=url,
            )
            session.commit()
            print(f"  -> {outcome.action} {outcome.new_state}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
