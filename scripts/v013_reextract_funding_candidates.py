"""Re-extraction of the approved corpus, without publishing anything.

The previous phase measured, read-only, that the widened funding taxonomy
classifies 69 of the 400 stored pages instead of 39 — but measurement is not
application, and the 40 approved records still publish their old values.

Writing the new values straight onto a `Scholarship` row is the defect
`scholarship_candidate_revision` exists to prevent: it mutates public data with
no state transition and no audit row. So this script re-extracts each approved
record from its stored page and hands every change to
`ReviewService.propose_candidate`, which records a proposal and publishes
nothing. A reviewer remains the only party who can change a published value.

    PYTHONPATH=. .venv/Scripts/python.exe scripts/v013_reextract_funding_candidates.py
    PYTHONPATH=. .venv/Scripts/python.exe scripts/v013_reextract_funding_candidates.py --dry-run

`--dry-run` writes nothing and is the default safety check before a real run.
"""

from __future__ import annotations

import argparse
from collections import Counter

from dotenv import load_dotenv
from sqlalchemy import select

from database.models.raw_document import RawDocument
from database.models.scholarship import Scholarship
from database.session import SessionLocal
from services.ingestion.cleaner import clean
from services.ingestion.loader import LoadedDocument
from services.ingestion.real_extractor import DeterministicLLMClient
from services.review import ReviewService
from services.scholarship.identity import canonical_url

load_dotenv(".env")

# Fields this script is allowed to propose. Funding only: everything else the
# extractor touches is either already published or governed by a different
# review path.
PROPOSABLE_FIELDS = ("funding_type",)

# A proposed classification must be *stated by the sentence the extractor
# cited*. Without this check the script happily proposes values the evidence
# does not support — measured on the live corpus, a page whose cited evidence
# was a benefits table with no mention of travel was proposed as
# "Travel Support", and a page whose cited evidence was a list of partner
# universities was proposed as "Fully Funded".
#
# Deliberately narrow: a proposal this guard blocks is left for a human, which
# costs a reviewer one row and costs nothing in correctness.
_SUPPORT_TERMS = {
    "Fully Funded": ("full tuition", "fully funded", "full cost", "all expenses", "full coverage"),
    "Partial Funded": ("partial", "partially", "up to", "percentage of tuition", "tuition reduction"),
    "Tuition Only": ("tuition fee", "tuition fees", "tuition"),
    "Tuition Waiver": ("waiver", "waived", "waive", "full tuition waiver"),
    "Stipend Only": ("stipend",),
    "Living Allowance": ("living allowance", "study allowance", "rent subsidy", "accommodation", "monthly allowance"),
    "Travel Support": ("travel", "airfare", "air fare", "flight", "round-trip"),
    "Research Funding": ("research", "research grant", "research allowance"),
}


def _is_supported(value: str | None, evidence: dict | None) -> bool:
    """Whether the cited evidence actually states this classification."""
    if value is None:
        # Proposing an empty value would *erase* a published, human-verified
        # classification on the strength of an extractor no longer recognising
        # it. That is a downgrade, and downgrades are not automatic.
        return False
    terms = _SUPPORT_TERMS.get(value)
    if terms is None:
        return False
    statement = str((evidence or {}).get("statement") or "").casefold()
    if not statement:
        return False
    return any(term in statement for term in terms)


def _documents_by_url(session) -> dict[str, RawDocument]:
    """Index stored pages by canonical URL.

    `scholarship.official_page_url` and `raw_document.source_url` have no
    foreign key between them, so the join is by URL. Canonicalising both
    sides means a page stored with a trailing slash or a tracking parameter
    still matches its record.
    """
    index: dict[str, RawDocument] = {}
    for document in session.execute(select(RawDocument)).scalars():
        key = canonical_url(document.source_url)
        if key:
            index.setdefault(key, document)
    return index


def _reextract(client, document: RawDocument) -> dict:
    cleaned = clean(
        LoadedDocument(
            document_id=str(document.document_id),
            source_id=str(document.source_id),
            source_url=document.source_url,
            content_type=document.content_type,
            raw_content=document.raw_content,
        )
    )
    return client.extract_scholarship(
        clean_text=cleaned.clean_text,
        source_url=document.source_url,
        default_country="JP",
        page_title=cleaned.page_title,
        headings=cleaned.headings,
        anchors=cleaned.anchors,
        looks_like_index=cleaned.looks_like_index,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="report what would be proposed without writing (default)",
    )
    parser.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="actually write the candidate revisions",
    )
    args = parser.parse_args()

    session = SessionLocal()
    client = DeterministicLLMClient()
    documents = _documents_by_url(session)

    approved = (
        session.execute(select(Scholarship).where(Scholarship.extraction_status == "approved"))
        .scalars()
        .all()
    )

    proposed = 0
    unchanged = 0
    no_page = 0
    errors = 0
    blocked = 0
    would_clear = 0
    reclassify = 0
    proposed_values: Counter = Counter()

    for record in approved:
        document = documents.get(canonical_url(record.official_page_url) or "")
        if document is None:
            no_page += 1
            continue
        try:
            result = _reextract(client, document)
        except Exception:  # noqa: BLE001 — an unparseable page is a data fact
            errors += 1
            continue

        observed = {field: result.get(field) for field in PROPOSABLE_FIELDS}
        if all(observed[field] == getattr(record, field) for field in PROPOSABLE_FIELDS):
            unchanged += 1
            continue

        # Never propose a classification the cited evidence does not state.
        evidence = (result.get("_extraction") or {}).get("funding_evidence")
        if not _is_supported(result.get("funding_type"), evidence):
            blocked += 1
            if record.funding_type and result.get("funding_type") is None:
                would_clear += 1
            continue

        # Only ever *fill* an empty value. Replacing a classification a
        # reviewer already approved is a reclassification, and the extractor
        # is not the authority on it: measured on the live corpus it wanted to
        # narrow four human-approved "Fully Funded" MEXT awards to "Travel
        # Support", which is true of one benefit and false of the award.
        if record.funding_type:
            reclassify += 1
            continue

        proposed_values[str(result.get("funding_type"))] += 1
        if args.dry_run:
            proposed += 1
            continue

        ReviewService(session).propose_candidate(
            record,
            observed=observed,
            actor="v013-funding-reextraction",
            origin="reacquisition",
            source_url=document.source_url,
            raw_document_id=str(document.document_id),
            reason=(
                "Re-extracted from the stored page under the widened funding "
                "vocabulary. Published value is unchanged until a reviewer acts."
            ),
        )
        proposed += 1

    if not args.dry_run:
        session.commit()

    print(f"mode                    : {'DRY RUN (nothing written)' if args.dry_run else 'APPLIED'}")
    print(f"approved records        : {len(approved)}")
    print(f"no stored page to match : {no_page}")
    print(f"re-extraction errors    : {errors}")
    print(f"funding already correct : {unchanged}")
    print(f"changes proposed        : {proposed}")
    print(f"blocked: unsupported    : {blocked}")
    print(f"  of which would clear a published value: {would_clear}")
    print(f"blocked: reclassification of an approved value: {reclassify}")
    if proposed_values:
        print()
        print("proposed new values:")
        for name, count in proposed_values.most_common():
            print(f"   {name:20s} {count}")

    session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
