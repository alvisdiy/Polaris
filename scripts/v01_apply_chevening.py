"""Phase 2D — the three Chevening records.

Phase 2B left them alone because their URLs were already live, so there was
no field change to make and ``correct()`` — correctly — refused to record a
correction that changed nothing. That left them as the only approved records
with no version row and no provenance.

Reading their pages properly does produce a real correction, and it is the
opposite of what the seed script claimed:

* the ASEAN page says "The Chevening ASEAN Scholarship is open to all fields
  of study. There are no specific subject areas prioritised", against a
  hand-typed list of five subjects;
* the SIDS page lists four development-priority areas the course must
  address, against a hand-typed list that shares only one of them;
* the umbrella page states no subject restriction at all, against six
  hand-typed subjects.

On funding, none of the three pages says "fully funded". The umbrella page
chevening.org/scholarships/ does: "Chevening Scholarships are fully-funded,
leaving you free to focus on achieving your professional goals". The ASEAN
and SIDS pages place themselves inside that programme — "As part of the
prestigious Chevening Scholarship programme, ASEAN applicants can apply for
all the standard benefits". funding_type is therefore kept, and the reason
names the page that carries the wording, since the evidence_url column holds
one URL and the funding wording is not on the programme page.

    python scripts/v01_apply_chevening.py --dry-run
    python scripts/v01_apply_chevening.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.models.scholarship_review_action import ReviewSource  # noqa: E402
from database.session import SessionLocal  # noqa: E402

ACTOR = "v01-ship-review"

UMBRELUS = "https://www.chevening.org/scholarships/"
UMBRELUS_WORDING = (
    "chevening.org/scholarships/ states 'Chevening Scholarships are "
    "fully-funded, leaving you free to focus on achieving your professional "
    "goals and maximising the experience of a lifetime'"
)

# (record name, its own page, field_of_study to publish, why)
CORRECTIONS = [
    (
        "Chevening ASEAN Scholarship",
        "https://www.chevening.org/asean-chevening-scholarship/",
        [],
        "the page states 'The Chevening ASEAN Scholarship is open to all "
        "fields of study. There are no specific subject areas prioritised "
        "for this scholarship', so the five hand-typed subjects are removed. "
        f"funding_type 'Fully Funded' is kept: the page places this "
        f"scholarship inside the Chevening Scholarship programme ('As part of "
        f"the prestigious Chevening Scholarship programme, ASEAN applicants "
        f"can apply for all the standard benefits') and {UMBRELUS_WORDING}",
    ),
    (
        "Chevening SIDS Scholarship",
        "https://www.chevening.org/sids-chevening-scholarship/",
        [
            "Human rights, democracy, and the rule of law",
            "Climate change and sustainability",
            "Economic recovery and growth",
            "Supportive societies that help people lead peaceful and productive lives",
        ],
        "the page says applicants 'are required to study on courses that help "
        "to address a national development priority or capacity shortage. "
        "This includes courses relating to: Human rights, democracy, and the "
        "rule of law; Climate change and sustainability; Economic recovery and "
        "growth; Supportive societies that help people lead peaceful and "
        "productive lives', replacing the hand-typed subjects, three of which "
        "the page does not mention. funding_type 'Fully Funded' is kept: the "
        "page places this scholarship inside the Chevening Scholarship "
        f"programme ('In addition to the standard benefits of a Chevening "
        f"Scholarship, the Chevening SIDS Scholarship includes an enhanced UK "
        f"programme') and {UMBRELUS_WORDING}",
    ),
    (
        "Chevening Scholarships",
        UMBRELUS,
        [],
        "the page states no subject restriction — it is the programme's front "
        "page, describing one-year master's degrees in the UK for applicants "
        "from all over the world — so the six hand-typed subjects are removed. "
        f"funding_type 'Fully Funded' is kept on this page's own wording: "
        f"{UMBRELUS_WORDING}",
    ),
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="print without writing"
    )
    args = parser.parse_args(argv)

    from sqlalchemy import select

    from database.models.scholarship import Scholarship
    from services.review.service import ReviewService

    session = SessionLocal()
    try:
        service = ReviewService(session)
        for name, url, fields, reason in CORRECTIONS:
            record = session.execute(
                select(Scholarship).where(Scholarship.scholarship_name == name)
            ).scalar_one_or_none()
            if record is None:
                raise SystemExit(f"record not found: {name}")
            if list(record.field_of_study or []) == fields:
                print(f"NO CHANGE  {name}")
                continue
            print(f"CORRECT    {name}")
            print(f"  before   {record.field_of_study}")
            print(f"  after    {fields}")
            if args.dry_run:
                continue
            outcome = service.correct(
                str(record.scholarship_id),
                actor=ACTOR,
                changes={"field_of_study": fields},
                reason=reason,
                source=ReviewSource.ADMIN_API,
                evidence_url=url,
                requeue=False,
            )
            session.commit()
            print(f"  -> {outcome.action} {outcome.new_state} version={outcome.version_id}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
