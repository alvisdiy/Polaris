"""Post-M10 Priority E — retire the orphan records whose pages are not scholarships.

M8 stored "Unknown Scholarship" as an identity. M9 quarantined those records
rather than deleting them. This retires the subset whose official page
demonstrably is not a scholarship at all — a login redirect, an FAQ page, a
grants index — using the existing reasoned-retirement path.

Deliberately *not* done here:

  * no `DELETE`, and no `UPDATE` of `extraction_status`;
  * no version, review action or provenance is invented: every one of these is
    written by `ReviewService.reject()`, which is the only writer of that
    column;
  * the records that today's extractor *can* now name are left alone. They
    are not corrupt; they are un-curated, and curating them is Priority H's
    job with a human reading the page.

Run with --apply to commit; the default is a dry run.
"""

from __future__ import annotations

import argparse

from sqlalchemy import text

from database.session import SessionLocal
from services.ingestion.cleaner import clean
from services.ingestion.loader import LoadedDocument
from services.ingestion.real_extractor import DeterministicLLMClient
from services.review.service import ReviewService

ACTOR = "post-m10-reviewer"

# Why each page is not a scholarship. Written per record rather than derived
# from a rule, because "this URL is a login page" is a judgement a reviewer
# makes by looking at it, not something a pattern can establish.
REASONS = {
    "31799c2b-0e04-4e1e-90b1-1fa844ba7d8f": (
        "The stored page for this URL is a login redirect "
        "(www2.naz.edu/auth/login?returnURL=...), not a scholarship page. "
        "M8 stored 'Unknown Scholarship' because the fetch landed on an "
        "authentication screen. There is no scholarship here to recover."
    ),
    "238df168-b049-4bb7-bf2d-afd36d292bfb": (
        "The official page is 'FAQs on scholarships | NTU Singapore' — a "
        "question-and-answer page about the scholarship application process. "
        "It describes no single award. Today's extractor refuses it too "
        "('describes a page section or interface element, not a programme')."
    ),
    "588192b0-4731-43ab-a22f-845507633848": (
        "The official page is the JSPS research-grant programme index "
        "(科学研究費助成事業). It lists grant schemes across every research "
        "field; there is no single scholarship on it. The cleaner classifies "
        "the page as an index."
    ),
    "38d37e1b-69c9-437c-840e-e430f4bc19d0": (
        "The official page is 'Scholarships & Funding - DAAD', a portal linking "
        "to many separate DAAD programmes. It is a route to scholarships, not "
        "one. Today's extractor produces no name for it."
    ),
    "c8ee75c6-6bc1-4a4e-aac4-b006fba828a0": (
        "The official page is 'Scholarships - Rosa-Luxemburg-Stiftung', an "
        "index of the foundation's various funding schemes, classified as an "
        "index by the cleaner. No single award is described."
    ),
    "0225bf46-119b-4f9b-afac-55bee16ff07e": (
        "The official page is 'Tuition and Scholarships | The University of "
        "Tokyo' — a fees-and-funding overview describing the university's "
        "tuition policy and its range of support, not one scholarship. "
        "Today's extractor produces no name for it."
    ),
}

ORPHANS_SQL = """
SELECT s.scholarship_id, s.scholarship_name, s.official_page_url
FROM scholarship s
WHERE s.scholarship_name ILIKE 'unknown%'
ORDER BY s.created_at
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit the retirements")
    args = parser.parse_args()

    client = DeterministicLLMClient()
    session = SessionLocal()
    retired = 0
    try:
        orphans = session.execute(text(ORPHANS_SQL)).fetchall()
        print(f"quarantined records: {len(orphans)}\n")

        for scholarship_id, name, url in orphans:
            scholarship_id = str(scholarship_id)
            document = session.execute(
                text(
                    "SELECT document_id, source_id, raw_content FROM raw_document "
                    "WHERE source_url = :u ORDER BY fetched_at DESC LIMIT 1"
                ),
                {"u": url},
            ).fetchone()
            if document is None:
                disposition = "KEEP PENDING — no stored page to re-extract"
            else:
                doc_id, source_id, raw = document
                cleaned = clean(
                    LoadedDocument(
                        document_id=str(doc_id),
                        source_id=str(source_id),
                        source_url=url,
                        content_type="html",
                        raw_content=raw,
                    )
                )
                payload = client.extract_scholarship(
                    clean_text=cleaned.clean_text,
                    source_url=url,
                    page_title=cleaned.page_title,
                    headings=tuple(cleaned.headings),
                    anchors=tuple(cleaned.anchors),
                    looks_like_index=cleaned.looks_like_index,
                )
                if payload.get("scholarship_name"):
                    disposition = "KEEP PENDING — today's extractor can now name it"
                else:
                    disposition = "RETIRE — today's extractor also finds nothing"

            reason = REASONS.get(scholarship_id)
            print(f"{scholarship_id}  {url}")
            print(f"  {disposition}")
            if reason is None and disposition.startswith("RETIRE"):
                print("  no written reason — left pending")
                continue
            if reason:
                print(f"  reason: {reason[:140]}...")
            if not disposition.startswith("RETIRE"):
                continue

            if not args.apply:
                print("  (dry run; pass --apply to commit)")
                continue

            service = ReviewService(session)
            outcome = service.reject(
                scholarship_id,
                actor=ACTOR,
                reason=reason,
                evidence_url=url,
            )
            session.commit()
            retired += 1
            print(f"  {outcome.previous_state} -> {outcome.new_state} (version {outcome.version_id})")

        if args.apply:
            print(f"\nretired {retired} records")
            leaked = [
                s.scholarship_name
                for s in session.execute(text(ORPHANS_SQL)).fetchall()
            ]
            print(f"records still named 'Unknown Scholarship': {len(leaked)}")
            published_leak = session.execute(
                text(
                    "SELECT count(*) FROM scholarship "
                    "WHERE scholarship_name ILIKE 'unknown%' "
                    "AND extraction_status = 'approved'"
                )
            ).scalar()
            print(f"of which published: {published_leak}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
