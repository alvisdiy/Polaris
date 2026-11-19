"""Phase 2B evidence review: what do the stored documents say about 'Fully Funded'?

Read-only. Prints, per approved record with funding_type == 'Fully Funded', the
sentences in its linked raw documents that mention funding wording. Documents are
linked through field_provenance raw_document_id, falling back to source_url match.
"""

from __future__ import annotations

import re

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

load_dotenv(".env")

from database.models.raw_document import RawDocument  # noqa: E402
from database.models.scholarship import Scholarship  # noqa: E402
from database.session import SessionLocal  # noqa: E402

FUNDING_TERMS = (
    r"fully[- ]funded|full[- ]funding|"
    r"tuition[^.]{0,60}(?:exempt|waiv|cover|paid|not cover|not includ)|"
    r"(?:exempt|waiv)[^.]{0,40}tuition|"
    r"(?:monthly )?(?:stipend|allowance)|"
    r"does not cover|no tuition|scholarship amount"
)
SENTENCE = re.compile(r"[^.\n]{0,140}(?:" + FUNDING_TERMS + r")[^.\n]{0,200}", re.IGNORECASE)


def linked_documents(session: Session, s: Scholarship) -> list[RawDocument]:
    prov = s.field_provenance or {}
    ids = {
        p.get("raw_document_id")
        for p in prov.values()
        if isinstance(p, dict) and p.get("raw_document_id")
    }
    docs: list[RawDocument] = []
    if ids:
        docs = list(
            session.execute(
                select(RawDocument).where(RawDocument.document_id.in_(ids))
            ).scalars()
        )
    if not docs and s.official_page_url:
        docs = list(
            session.execute(
                select(RawDocument).where(
                    RawDocument.source_url == s.official_page_url
                )
            ).scalars()
        )
    return docs


def main() -> None:
    session = SessionLocal()
    try:
        rows = session.execute(
            select(Scholarship).where(
                Scholarship.extraction_status == "approved",
                Scholarship.funding_type == "Fully Funded",
            )
        ).scalars().all()
        print(f"approved + funding_type='Fully Funded': {len(rows)}\n")
        for s in sorted(rows, key=lambda r: r.scholarship_name or ""):
            print("=" * 78)
            print(f"{s.scholarship_id}  {s.scholarship_name}")
            print(f"  degree={s.degree!r}  url={s.official_page_url}")
            docs = linked_documents(session, s)
            if not docs:
                print("  NO LINKED DOCUMENT -- no recorded source wording available")
            for d in docs:
                print(
                    f"  doc {d.document_id} {d.source_url} "
                    f"bytes={len(d.raw_content or '')}"
                )
                for m in SENTENCE.finditer(d.raw_content or ""):
                    print("    | " + " ".join(m.group(0).split())[:240])
    finally:
        session.close()


if __name__ == "__main__":
    main()
