"""M10: print the cleaned text of real stored pages, to curate expectations.

Read-only. The golden dataset may only assert a fact the official page
actually states, which means someone has to read the pages. This is the tool
for doing that: it runs the real cleaner over real ``RawDocument`` rows and
prints what the extractor is allowed to see.

    python scripts/m10_show_pages.py                 # one page per source
    python scripts/m10_show_pages.py --url ...       # pages matching a substring
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.models.raw_document import RawDocument  # noqa: E402
from database.models.source_registry import SourceRegistry  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.ingestion.cleaner import clean  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="", help="substring match on source_url")
    parser.add_argument("--limit", type=int, default=1, help="max pages per source")
    parser.add_argument("--chars", type=int, default=2500)
    args = parser.parse_args()

    session = SessionLocal()
    try:
        query = session.query(RawDocument, SourceRegistry).join(
            SourceRegistry, RawDocument.source_id == SourceRegistry.source_id
        )
        if args.url:
            query = query.filter(RawDocument.source_url.ilike(f"%{args.url}%"))
        rows = query.order_by(RawDocument.fetched_at.desc()).all()

        seen: set = set()
        shown = 0
        for doc, source in rows:
            if shown >= args.limit:
                break
            key = source.source_id
            if not args.url and key in seen:
                continue
            seen.add(key)
            document = clean(
                _loaded(doc)
            )
            print("=" * 100)
            print(f"source_url : {doc.source_url}")
            print(f"source     : {source.source_name}")
            print(f"title      : {document.page_title}")
            print(f"headings   : {document.headings[:8]}")
            print(f"index      : {document.looks_like_index}")
            print(f"--- clean text ({len(document.clean_text)} chars) ---")
            print(document.clean_text[: args.chars])
            shown += 1
    finally:
        session.close()


def _loaded(doc: RawDocument):
    from services.ingestion.loader import LoadedDocument

    return LoadedDocument(
        document_id=str(doc.document_id),
        source_id=str(doc.source_id),
        source_url=doc.source_url,
        content_type=doc.content_type,
        raw_content=doc.raw_content,
    )


if __name__ == "__main__":
    main()
