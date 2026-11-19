"""V0.1 Phase 2A — re-verify the legacy approved records against their live sources.

The 19 records that publish without any recorded review action, version or
provenance were seeded by hand (scripts/seed_manual_scholarships.py), so their
`funding_type="Fully Funded"` and their `field_of_study` lists were typed by a
developer, never read off a page. That is exactly the class of claim this
phase exists to test.

This script fetches each record's official page through the existing
``GenericHTTPConnector`` (SafeFetch: SSRF validation, robots, redirects),
runs the same deterministic extractor production uses, and prints what the
live source says next to what is published. It writes documents to
``raw_document`` so the comparison is reproducible from stored evidence, but
it changes no scholarship field and writes no review action.

    python scripts/v01_verify_legacy.py            # report only
    python scripts/v01_verify_legacy.py --fetch    # also (re)fetch live pages
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402

LEGACY_SQL = """
SELECT s.scholarship_id, s.scholarship_name, s.official_page_url, s.application_url,
       s.degree, s.funding_type, s.field_of_study, s.source_id,
       p.provider_name, c.name AS country
FROM scholarship s
LEFT JOIN provider p ON p.provider_id = s.provider_id
LEFT JOIN country  c ON c.country_id  = s.country_id
WHERE s.extraction_status = 'approved'
  AND NOT EXISTS (
      SELECT 1 FROM scholarship_review_action ra
      WHERE ra.scholarship_id = s.scholarship_id AND ra.action = 'approved'
  )
ORDER BY s.scholarship_name
"""


def _config(source_id, url: str):
    from services.ingestion.connectors.base_connector import ConnectorConfig

    return ConnectorConfig(
        source_id=source_id,
        url=url,
        timeout=30,
        user_agent="PolarisBot/0.3 (+V0.1 legacy verification; contact: research)",
    )


def _extract(session, document):
    """Run production cleaning + extraction on a stored document."""
    from services.ingestion.cleaner import clean
    from services.ingestion.loader import LoadedDocument
    from services.ingestion.real_extractor import DeterministicLLMClient

    cleaned = clean(
        LoadedDocument(
            document_id=str(document.document_id),
            source_id=str(document.source_id),
            source_url=document.source_url,
            content_type=document.content_type,
            raw_content=document.raw_content,
        )
    )
    payload = DeterministicLLMClient().extract_scholarship(
        clean_text=cleaned.clean_text,
        source_url=document.source_url,
        page_title=cleaned.page_title,
        headings=tuple(cleaned.headings),
        anchors=tuple(cleaned.anchors),
        looks_like_index=cleaned.looks_like_index,
    )
    payload.pop("_extraction", None)
    return cleaned, payload


def _funding_wording(session, document) -> str | None:
    """The exact sentence the stored page used about funding, if any."""
    from services.ingestion.cleaner import clean
    from services.ingestion.loader import LoadedDocument

    cleaned = clean(
        LoadedDocument(
            document_id=str(document.document_id),
            source_id=str(document.source_id),
            source_url=document.source_url,
            content_type=document.content_type,
            raw_content=document.raw_content,
        )
    )
    for sentence in cleaned.clean_text.split(". "):
        low = sentence.lower()
        if "full tuition" in low or "fully funded" in low or "full funding" in low:
            return " ".join(sentence.split())[:220]
    return None


async def main_async(args) -> int:
    from services.ingestion.connectors.generic_connector import GenericHTTPConnector
    from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
    from services.ingestion.repositories.raw_document_repository import (
        RawDocumentRepository,
    )

    session = SessionLocal()
    raw_repo = RawDocumentRepository(session)
    mapper = RawDocumentMapper()
    try:
        records = [dict(r) for r in session.execute(text(LEGACY_SQL)).mappings()]
        print(f"legacy approved records: {len(records)}\n")

        for rec in records:
            url = rec["official_page_url"]
            print("=" * 100)
            print(f"{rec['scholarship_name']}")
            print(f"  official  {url}")
            print(f"  apply     {rec['application_url']}")
            print(f"  provider  {rec['provider_name']}   country {rec['country']}")
            print(
                f"  published degree={rec['degree']!r} funding={rec['funding_type']!r} "
                f"fields={rec['field_of_study']}"
            )

            document = session.execute(
                text(
                    "SELECT document_id FROM raw_document "
                    "WHERE source_url = :u ORDER BY fetched_at DESC LIMIT 1"
                ),
                {"u": url},
            ).scalar_one_or_none()

            if args.fetch:
                connector = GenericHTTPConnector(
                    _config(rec["source_id"], url)
                )
                try:
                    fetch = await connector.fetch(url)
                    candidate = mapper.to_orm(fetch)
                    existing = raw_repo.get_by_source_and_checksum(
                        candidate.source_id, candidate.checksum
                    )
                    document = (
                        str(existing.document_id)
                        if existing
                        else str(raw_repo.save(candidate).document_id)
                    )
                    session.commit()
                    print(f"  fetched   document_id={document}")
                except Exception as exc:  # noqa: BLE001 — a refused fetch is a result
                    print(f"  FETCH FAILED {type(exc).__name__}: {str(exc)[:160]}")
                    if document is None:
                        continue
                finally:
                    try:
                        await connector.close()
                    except Exception:  # noqa: BLE001
                        pass

            if document is None:
                print("  no stored document for this URL — nothing to compare")
                continue

            doc = raw_repo.get_by_id(document)
            cleaned, payload = _extract(session, doc)
            print(f"  page      title={cleaned.page_title!r} index={cleaned.looks_like_index}")
            print(f"  extracted name={payload.get('scholarship_name')!r}")
            print(f"            degree={payload.get('degree')!r} funding={payload.get('funding_type')!r}")
            print(f"            fields={payload.get('field_of_study')}")
            wording = _funding_wording(session, doc)
            print(f"  funding wording on page: {wording!r}")
    finally:
        session.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="re-fetch each official page live through SafeFetch before comparing",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
