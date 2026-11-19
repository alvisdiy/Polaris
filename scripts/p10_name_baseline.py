"""Post-M10 Priority B baseline — why each golden name is right or wrong.

Prints the extracted name, the reference, and every candidate the identity
gate considered, so the ranking defect can be read directly rather than
inferred from a score.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from database.session import SessionLocal
from services.ingestion.cleaner import clean
from services.ingestion.loader import LoadedDocument
from services.ingestion.real_extractor import DeterministicLLMClient


def main() -> None:
    golden = json.load(open("tests/golden/extraction_golden.json", encoding="utf-8"))
    client = DeterministicLLMClient()
    session = SessionLocal()
    try:
        for sample in golden["samples"]:
            row = session.execute(
                text(
                    "SELECT d.document_id, d.source_id, d.raw_content "
                    "FROM raw_document d WHERE d.document_id = CAST(:d AS uuid)"
                ),
                {"d": sample["document_id"]},
            ).fetchone()
            if row is None:
                print(f"!! {sample['id']}: no stored document")
                continue
            doc_id, source_id, raw = row
            cleaned = clean(
                LoadedDocument(
                    document_id=str(doc_id),
                    source_id=str(source_id),
                    source_url=sample["url"],
                    content_type="html",
                    raw_content=raw,
                )
            )
            extracted = client.extract_scholarship(
                clean_text=cleaned.clean_text,
                source_url=sample["url"],
                page_title=cleaned.page_title,
                headings=tuple(cleaned.headings),
                anchors=tuple(cleaned.anchors),
                looks_like_index=cleaned.looks_like_index,
            )
            name = extracted.get("scholarship_name")
            reference = sample.get("name_reference")
            ok = (name or None) == reference
            print("=" * 95)
            print(f"{sample['id']}  {'OK ' if ok else 'BAD'}")
            print(f"  title     : {cleaned.page_title!r}")
            print(f"  index?    : {cleaned.looks_like_index}")
            print(f"  headings  : {cleaned.headings[:8]}")
            print(f"  reference : {reference!r}")
            print(f"  extracted : {name!r}")
            verdict = (extracted.get("_extraction") or {}).get("name_verdict") or {}
            print(f"  verdict   : {json.dumps(verdict, ensure_ascii=False)[:300]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
