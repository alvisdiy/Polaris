"""Post-M10 §A — replay the real cleaner + extractor over the 8 pilot documents.

The question this answers is not "what did the extractor produce" (the DB
already says that) but "what did the pipeline *know* about the page when it
produced it" — in particular whether the cleaner's ``looks_like_index``
classification was already available and simply not acted on.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from database.session import SessionLocal
from services.ingestion.cleaner import clean
from services.ingestion.loader import LoadedDocument
from services.ingestion.real_extractor import DeterministicLLMClient

DOC_SQL = """
SELECT s.scholarship_name, s.official_page_url,
       (s.field_provenance -> 'degree' ->> 'document_id')::uuid
FROM scholarship s
WHERE s.provenance_origin = 'exploration'
  AND s.extraction_status = 'pending_review'
"""


def main() -> None:
    client = DeterministicLLMClient()
    session = SessionLocal()
    try:
        rows = session.execute(text(DOC_SQL)).fetchall()
        print(f"replaying {len(rows)} pilot documents\n")
        for name, url, doc_id in rows:
            raw = session.execute(
                text("SELECT raw_content FROM raw_document WHERE document_id = :d"),
                {"d": doc_id},
            ).scalar() or ""
            cleaned = clean(
                LoadedDocument(
                    document_id=str(doc_id),
                    source_id="",
                    source_url=url,
                    content_type="html",
                    raw_content=raw,
                )
            )
            extracted = client.extract_scholarship(
                clean_text=cleaned.clean_text,
                source_url=url,
                page_title=cleaned.page_title,
                headings=cleaned.headings,
                anchors=cleaned.anchors,
                looks_like_index=cleaned.looks_like_index,
            )
            meta = extracted.get("_extraction", {})
            print("=" * 90)
            print(f"stored name : {name}")
            print(f"page_title  : {cleaned.page_title!r}")
            print(f"looks_like_index: {cleaned.looks_like_index}")
            print(f"hidden_markers  : {cleaned.hidden_instruction_markers}")
            print(f"headings[:6]: {cleaned.headings[:6]}")
            print(f"new name   : {extracted.get('scholarship_name')!r}")
            print(f"provider   : {extracted.get('provider_name')!r}")
            print(f"degree     : {extracted.get('degree')!r}  funding={extracted.get('funding_type')!r}")
            print(f"deadline   : {extracted.get('application_deadline')!r}")
            print(f"meta keys  : {sorted(meta)}")
            for key in ("name_reasons", "degree_candidates", "name_verdict"):
                if key in meta:
                    print(f"  {key}: {json.dumps(meta[key], ensure_ascii=False)[:400]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
