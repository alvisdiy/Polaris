"""M11 — evaluate the page-intent classifier over every stored document."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


from database.models.raw_document import RawDocument  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.exploration.page_intent import PageIntent, classify_page_intent  # noqa: E402
from services.ingestion.cleaner import clean  # noqa: E402
from services.ingestion.loader import LoadedDocument  # noqa: E402


def main() -> None:
    session = SessionLocal()
    docs = session.query(RawDocument).order_by(RawDocument.fetched_at.desc()).all()
    latest: dict[str, RawDocument] = {}
    for d in docs:
        latest.setdefault(d.source_url, d)
    print(f"{len(docs)} documents, {len(latest)} distinct URLs\n")

    tally = Counter()
    by_intent: dict[str, list[tuple[str, str]]] = {}
    for url, doc in latest.items():
        if doc.content_type != "html":
            tally["NON_HTML"] += 1
            continue
        cleaned = clean(
            LoadedDocument(
                document_id=str(doc.document_id),
                source_id=str(doc.source_id),
                source_url=url,
                content_type=doc.content_type,
                raw_content=doc.raw_content,
            )
        )
        r = classify_page_intent(
            url=url,
            page_title=cleaned.page_title,
            headings=cleaned.headings,
            anchors=cleaned.anchors,
            text=cleaned.clean_text,
        )
        tally[r.intent] += 1
        by_intent.setdefault(r.intent, []).append(
            (cleaned.page_title[:70] or "(no title)", url)
        )

    for intent, n in tally.most_common():
        print(f"{n:>4}  {intent}")
    print()
    for intent in (
        PageIntent.SCHOLARSHIP_DETAIL,
        PageIntent.SCHOLARSHIP_INDEX,
        PageIntent.SCHOLARSHIP_OVERVIEW,
        PageIntent.UNKNOWN,
        PageIntent.FAQ,
        PageIntent.IRRELEVANT,
    ):
        print(f"--- {intent} ({tally.get(intent, 0)})")
        for title, url in sorted(by_intent.get(intent, []))[:12]:
            print(f"      {title!r}\n          {url[:110]}")
    session.close()


if __name__ == "__main__":
    main()

