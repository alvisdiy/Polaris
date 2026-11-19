"""Post-M10 Priority E — what the improved extractor makes of the 17 orphans.

M8 stored "Unknown Scholarship" as if it were an identity. M9 quarantined those
records rather than deleting them and M10 left them alone. Priority B changed
the name extractor substantially (5/12 -> 11/12 on the golden set), so the
question this answers is: with today's extractor, do those pages still yield
nothing, do they now yield a real name, or are they pages that describe no
single scholarship at all?

Read-only. It writes nothing: the point is to classify each record so the
decision to retire, re-extract or keep quarantined can be taken deliberately
through ReviewService rather than by deleting rows.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from database.session import SessionLocal
from services.ingestion.cleaner import clean
from services.ingestion.loader import LoadedDocument
from services.ingestion.real_extractor import DeterministicLLMClient

ORPHANS_SQL = """
SELECT s.scholarship_id, s.official_page_url, s.provider_id
FROM scholarship s
WHERE s.scholarship_name ILIKE 'unknown%'
ORDER BY s.created_at
"""


def main() -> None:
    client = DeterministicLLMClient()
    session = SessionLocal()
    try:
        orphans = session.execute(text(ORPHANS_SQL)).fetchall()
        print(f"quarantined records: {len(orphans)}\n")
        named = unnamed = 0
        for scholarship_id, url, provider_id in orphans:
            document = session.execute(
                text(
                    "SELECT document_id, source_id, raw_content FROM raw_document "
                    "WHERE source_url = :u ORDER BY fetched_at DESC LIMIT 1"
                ),
                {"u": url},
            ).fetchone()
            print("=" * 95)
            print(f"{scholarship_id}  {url}")
            if document is None:
                print("  no stored document for this URL — cannot re-extract")
                unnamed += 1
                continue
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
            meta = payload.pop("_extraction", {})
            name = payload.get("scholarship_name")
            verdict = meta.get("name_verdict") or {}
            print(f"  page title : {cleaned.page_title!r}")
            print(f"  index page : {cleaned.looks_like_index}")
            print(f"  name now   : {name!r}")
            print(f"  confidence : {verdict.get('confidence')}")
            print(f"  verdict    : {json.dumps(verdict.get('reasons'), ensure_ascii=False)[:220]}")
            if name:
                named += 1
                print("  -> would re-extract as a named scholarship")
            else:
                unnamed += 1
                print("  -> still nothing: the page names no single scholarship")
        print()
        print(f"would yield a name : {named}")
        print(f"still nameless      : {unnamed}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
