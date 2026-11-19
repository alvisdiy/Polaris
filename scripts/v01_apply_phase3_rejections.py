"""Phase 3 follow-up — reject what acquisition extracted but review refuses.

Phase 3 ran the real pipeline over frontier candidates and landed nine
records. Two passed the gate and were approved. Seven are sitting in review
blocked on ``degree``, and reading their documents shows why: they are not
scholarships.

Six came from wemakescholars.com, which is an aggregator. Its category pages
are titled "62+ Masters Scholarships in Singapore 2026-27" and
"Master's Scholarships", so the extractor produced a record *named after the
listing* with one of the listed awards as its body. The remaining two came from
a University of Tokyo calendar page and a page whose heading the extractor took
as the name ("1. Application Methods").

None of these can be corrected into a real record — the source page does not
describe one scholarship, so no field change would make it honest. They are
rejected with the reason written down, which is the outcome the state machine
has for exactly this.

Deliberately *not* approved with ``override_quality``: the gate was right
about these, and overriding it is how aggregator listings end up published as
scholarships.

    python scripts/v01_apply_phase3_rejections.py --dry-run
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
        "Public Service Commission (PSC) Masters Scholarships in Singapore 2027",
        "https://www.wemakescholars.com/masters-scholarships-for-international-students-in-singapore",
        "the source is an aggregator listing page titled '62+ Masters "
        "Scholarships in Singapore 2026-27', not a page for one scholarship. "
        "The extracted name is the listing's title and no single award is "
        "described, so there is nothing to correct this into",
    ),
    (
        "Centrally Sponsored Post-Matric Scholarship for ST Students",
        "https://www.wemakescholars.com/medicine-scholarships-for-international-students",
        "the source is an aggregator category page ('By Degree: Master's "
        "Scholarships, Bachelor's Scholarships, MBA Scholarships, Medicine "
        "(MBBS/MD) Scholarships'). The extracted name belongs to one entry in "
        "a list the page does not describe in full",
    ),
    (
        "Mirabelli Corporation MBA Scholarship at Lakehead University 2026",
        "https://www.wemakescholars.com/mba-scholarships-for-international-students",
        "the source is an aggregator category page, not a page for this award. "
        "The page links to it rather than stating its terms",
    ),
    (
        "Croucher Scholarships for Doctoral Study 2027",
        "https://www.wemakescholars.com/scholarships-to-study-in-australia-for-international-students",
        "the source is an aggregator category page, not a page for this award. "
        "The page links to it rather than stating its terms",
    ),
    (
        "IE University Scholarship for Indian students 2026",
        "https://www.wemakescholars.com/bachelors-scholarships-for-international-students",
        "the source is an aggregator category page, not a page for this award. "
        "The page links to it rather than stating its terms",
    ),
    (
        "Academic Year 2026",
        "https://www.u-tokyo.ac.jp/en/current-students/university_calendar.html",
        "the source is the university's academic calendar, not a scholarship. "
        "The extracted name is a column heading on that page",
    ),
    (
        "1. Application Methods",
        "https://www.u-tokyo.ac.jp/en/prospective-students/privateorg.html",
        "the source is a page about recognised external organisations, not a "
        "scholarship. The extracted name is a numbered section heading",
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
            print(f"REJECT   {name}\n  {reason[:100]}...")
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
