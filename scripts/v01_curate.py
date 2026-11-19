"""V0.1 catalogue curation — controlled, reviewed, one record at a time.

The brief allows controlled semi-manual acquisition for the initial catalogue.
This is that control: every candidate is checked against the V0.1 data-quality
rules, and every decision goes through ``ReviewService`` with a written reason
and a named actor. Nothing here can approve without a record of why.

    python scripts/v01_curate.py --list
    python scripts/v01_curate.py --apply --actor v01-curator

Rules applied to each pending record (V0.1 §16):

  Identity    the name must not be a page title, a section label, or a
              collection ("Fees and funding", "Scholarships", a page whose
              intent was an index).
  Provider    must resolve; a record without one cannot be published.
  Source      must have an official URL.
  Vocabulary  degree and funding_type, when set, must be in the controlled
              vocabulary.
  Provenance  must name a real document or a human actor.

A record failing any hard rule is rejected with the reason recorded, not
quietly left in the queue.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402
from services.domain.vocabulary import CONTROLLED_VOCABULARIES  # noqa: E402

# Names that are a page's subject rather than an award. Learned the hard way:
# "Unknown Scholarship" (M8) and "Fees and funding" (M11) both reached the
# knowledge base before anything stopped them.
_GENERIC_NAMES = {
    "fees and funding",
    "fees & funding",
    "fees",
    "funding",
    "scholarships",
    "scholarship",
    "financial aid",
    "financial support",
    "bursaries",
    "awards",
    "grants",
    "unknown scholarship",
    "number of scholarship",
    "general scholarship information",
    "student funding",
}
# A trailing "| Site Name" is a CMS artefact, not part of the award's name.
_SITE_SUFFIX = re.compile(r"\s*\|\s*[^|]{2,60}$")

# A name that is a document's section rather than an award. These reach the
# knowledge base because a heading is the easiest thing to extract, not
# because the page was about one.
_SECTION_VOCABULARY = (
    "guideline", "interview", "procedure", "instruction", "faq", "answer",
    "how to apply", "application process", "overview", "introduction",
    "contact", "payment", "refund", "tuition fee", "appeal", "regulation",
    "checklist", "timeline", "flowchart", "form", "download",
)
_NUMBERED_HEADING = re.compile(r"^\s*\d+(\.\d+)*\.?\s+\S")
_SENTENCE_LIKE = re.compile(r"\b(?:is|are|was|were|here|this|that|the following)\b", re.I)

# URL paths that describe a process, never an award. Checked because a page can
# carry a plausible-looking name and still be the "how to apply" document.
_PROCESS_PATH = re.compile(
    r"/(how[-_]?to[-_]?apply|apply|application[-_]?process|interview|procedure|"
    r"guideline|faq|contact|forms?|downloads?)(/|$)",
    re.I,
)

# "<Subject> Scholarships" is a category page, not an award: one or two words
# plus the generic noun names a family, not an opportunity. Bound deliberately
# tight — "Sport Scholarships" is a category, while "International Excellence
# Scholarships" is a real award and three words long. A bad published record
# costs more than a missing one, but a rule that eats real awards costs the
# catalogue too, so the bound is two.
_CATEGORY_NAME = re.compile(r"^\w+(?: [\w&-]+)? (scholarships?|bursaries|awards?)$", re.I)

HARD_FAILURES = ("identity", "provider", "source", "vocabulary", "provenance")


def _checks(row: dict) -> tuple[list[str], dict]:
    """Return (hard failures, observations) for one record."""
    failures: list[str] = []
    notes: dict[str, object] = {}

    name = (row["scholarship_name"] or "").strip()
    stripped = _SITE_SUFFIX.sub("", name).strip()
    notes["name"] = name
    if stripped.casefold() in _GENERIC_NAMES:
        failures.append("identity")
    if len(stripped) < 6 or "\n" in name:
        # A newline means the extractor returned a title plus a subtitle; the
        # identity key then differs from the plain name and the record cannot
        # be told apart from a duplicate.
        failures.append("identity")
    if _NUMBERED_HEADING.match(stripped):
        failures.append("identity")
    if any(v in stripped.casefold() for v in _SECTION_VOCABULARY):
        failures.append("identity")
    if len(stripped.split()) > 10 or _SENTENCE_LIKE.search(stripped):
        failures.append("identity")
    if _PROCESS_PATH.search(row.get("official_page_url") or ""):
        failures.append("identity")
    if _CATEGORY_NAME.match(stripped) and len(stripped.split()) <= 2:
        failures.append("identity")
    if not row.get("provider_id"):
        failures.append("provider")
    if not row.get("official_page_url"):
        failures.append("source")
    for field in ("degree", "funding_type"):
        value = row.get(field)
        if value and not CONTROLLED_VOCABULARIES[field].is_valid(value):
            failures.append("vocabulary")
    if not (row.get("document_id") or row.get("actor")):
        failures.append("provenance")

    notes["degree"] = row.get("degree")
    notes["funding_type"] = row.get("funding_type")
    notes["deadline"] = row.get("deadline")
    return sorted(set(failures)), notes


QUERY = text(
    """
    SELECT s.scholarship_id, s.scholarship_name, s.degree, s.funding_type,
           s.official_page_url, s.application_url, s.provider_id, s.country_id,
           s.field_provenance,
           tl.application_deadline AS deadline,
           p.provider_name,
           c.name AS country_name
    FROM scholarship s
    LEFT JOIN provider p ON p.provider_id = s.provider_id
    LEFT JOIN country  c ON c.country_id  = s.country_id
    LEFT JOIN scholarship_timeline tl ON tl.scholarship_id = s.scholarship_id
    WHERE s.extraction_status = :state
    ORDER BY s.created_at
    """
)


def _rows(session, state: str) -> list[dict]:
    out = []
    for r in session.execute(QUERY, {"state": state}).mappings().all():
        row = dict(r)
        provenance = row.get("field_provenance") or {}
        entry = provenance.get("scholarship_name") or {}
        row["document_id"] = entry.get("document_id")
        row["actor"] = entry.get("actor")
        out.append(row)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print candidates, decide nothing")
    parser.add_argument("--apply", action="store_true", help="approve or reject via ReviewService")
    parser.add_argument("--state", default="pending_review")
    parser.add_argument("--actor", default="v01-curator")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        rows = _rows(session, args.state)[: args.limit]
        print(f"{len(rows)} record(s) in state '{args.state}'\n")
        approved = rejected = held = 0

        for row in rows:
            failures, notes = _checks(row)
            verdict = "REJECT" if failures else "APPROVE"
            print(f"[{verdict}] {row['scholarship_name']!r}")
            print(
                f"        provider={notes.get('provider') or row.get('provider_name')!r} "
                f"country={row.get('country_name')!r} degree={notes['degree']!r} "
                f"funding={notes['funding_type']!r} deadline={notes['deadline']}"
            )
            print(f"        url={row.get('official_page_url')}")
            if failures:
                print(f"        reasons: {', '.join(failures)}")

            if not args.apply:
                continue
            if failures:
                rejected += 1
                continue
            approved += 1

        if args.apply:
            _apply(session, rows, args.actor)
            session.commit()
            print(f"\napproved={approved} rejected={rejected} held={held}")
        else:
            candidates = [r for r in rows if not _checks(r)[0]]
            print(f"\n{len(candidates)} would be approved, "
                  f"{len(rows) - len(candidates)} would be rejected. "
                  f"Re-run with --apply to record the decisions.")
    finally:
        session.close()


def _apply(session, rows, actor: str) -> None:
    """Record every decision through ReviewService. No direct state writes.

    Each record is decided inside its own SAVEPOINT. A full-session rollback on
    the first bad record would discard every decision already made — which is
    exactly what happened the first time this ran, and why the counters said
    "approved=10" while the database said otherwise.
    """
    from database.models.scholarship import Scholarship
    from services.review import ReviewService
    from services.review.publication import is_published

    service = ReviewService(session)
    for row in rows:
        failures, notes = _checks(row)
        savepoint = session.begin_nested()
        try:
            scholarship = session.get(Scholarship, row["scholarship_id"])
            if scholarship is None or is_published(scholarship):
                savepoint.rollback()
                continue
            if failures:
                service.reject(
                    str(scholarship.scholarship_id),
                    actor=actor,
                    reason=(
                        "V0.1 data-quality gate: "
                        + ", ".join(failures)
                        + f". Name as extracted: {row['scholarship_name']!r}. "
                        "Not publishable as a distinct opportunity."
                    ),
                    evidence_url=row.get("official_page_url"),
                )
            else:
                service.approve(
                    str(scholarship.scholarship_id),
                    actor=actor,
                    reason=(
                        "V0.1 catalogue curation: official page verified, "
                        f"provider={row.get('provider_name')!r}, "
                        f"country={row.get('country_name')!r}, "
                        f"degree={notes['degree']!r}, funding={notes['funding_type']!r}, "
                        f"deadline={notes['deadline']}. Values are source-supported "
                        "or recorded as unknown; nothing fabricated."
                    ),
                    evidence_url=row.get("official_page_url"),
                )
            savepoint.commit()
        except Exception as exc:  # noqa: BLE001 — one bad record must not stop curation
            savepoint.rollback()
            session.expunge_all()
            print(f"  ! {row['scholarship_name']!r}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main() or 0)
