"""Read-only measurement: funding-classification coverage over the stored corpus.

Answers one question with production data rather than fixtures: after the
funding taxonomy was widened from three values to eight, how many real stored
scholarship pages now carry a funding classification, and how many of those
carry source evidence for it?

Strictly read-only. Nothing is written to the database; the point is to size
the change before deciding whether to re-extract anything.

    PYTHONPATH=. .venv/Scripts/python.exe scripts/v012_funding_coverage_measure.py
"""

from __future__ import annotations

from collections import Counter

from dotenv import load_dotenv
from sqlalchemy import text

from database.session import SessionLocal
from services.domain.vocabulary import FUNDING_TYPE
from services.ingestion.cleaner import clean
from services.ingestion.loader import LoadedDocument
from services.ingestion.real_extractor import DeterministicLLMClient

load_dotenv(".env")


def main() -> int:
    session = SessionLocal()
    rows = session.execute(
        text(
            "SELECT document_id, source_id, source_url, content_type, raw_content "
            "FROM raw_document ORDER BY fetched_at DESC"
        )
    ).fetchall()

    classified = Counter()
    null_count = 0
    without_evidence = 0
    errors = 0
    previous = Counter()

    client = DeterministicLLMClient()
    # What the pre-expansion three-value vocabulary would have produced, for
    # the same pages, so the delta is measured rather than asserted.
    legacy_map = {
        "Fully Funded": "Fully Funded",
        "Partial Funded": "Partial Funded",
        "Tuition Only": "Tuition Only",
        "Tuition Waiver": "Tuition Only",
        "Stipend Only": "Tuition Only",
        "Living Allowance": None,
        "Travel Support": None,
        "Research Funding": None,
    }

    for row in rows:
        try:
            cleaned = clean(
                LoadedDocument(
                    document_id=str(row[0]),
                    source_id=str(row[1]),
                    source_url=row[2],
                    content_type=row[3],
                    raw_content=row[4],
                )
            )
            result = client.extract_scholarship(
                clean_text=cleaned.clean_text,
                source_url=row[2],
                default_country="JP",
                page_title=cleaned.page_title,
                headings=cleaned.headings,
                anchors=cleaned.anchors,
                looks_like_index=cleaned.looks_like_index,
            )
        except Exception:  # noqa: BLE001 — a page that cannot be parsed is data
            errors += 1
            continue

        value = result.get("funding_type")
        if value is None:
            null_count += 1
            previous["(null)"] += 1
        else:
            classified[value] += 1
            previous[legacy_map.get(value) or "(null)"] += 1
            if not (result.get("_extraction") or {}).get("funding_evidence"):
                without_evidence += 1

    total = len(rows)
    print(f"documents measured      : {total}")
    print(f"parse errors            : {errors}")
    print(f"funding classified      : {total - null_count - errors}")
    print(f"funding NULL            : {null_count}")
    print(f"classified w/o evidence : {without_evidence}")
    print()
    print("current 8-value vocabulary:")
    for name, count in classified.most_common():
        print(f"   {name:20s} {count}")
    print()
    print("what the old 3-value vocabulary would have produced:")
    for name, count in previous.most_common():
        print(f"   {name:20s} {count}")
    print()
    print(f"vocabulary size: {len(FUNDING_TYPE.order)} values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
