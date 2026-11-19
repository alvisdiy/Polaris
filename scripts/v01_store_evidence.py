"""Store evidence documents for verified live pages and print funding wording.

Phase 2A/2B needs the source's own words before any correction is written.
This fetches each verified URL through the existing connectors (no SafeFetch
bypass), stores the raw document through RawDocumentRepository so the
correction has a document to point at, and prints the sentences that speak to
tuition, stipends or full funding.

    python scripts/v01_store_evidence.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.session import SessionLocal  # noqa: E402

# Verified live during Phase 2A probing. Keyed by the record's current name.
TARGETS = [
    ("Australia Awards", "https://australiaawards.com.au/"),
    ("Chevening ASEAN Scholarship", "https://www.chevening.org/asean-chevening-scholarship/"),
    ("Chevening SIDS Scholarship", "https://www.chevening.org/sids-chevening-scholarship/"),
    ("Chevening Scholarships", "https://www.chevening.org/scholarships/"),
    ("DAAD Development-Related Postgraduate Courses (EPOS)",
     "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50076777"),
    ("DAAD Helmut-Schmidt-Programme",
     "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50026397"),
    ("DAAD Study Scholarships - Master Studies for All Academic Disciplines",
     "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/?detail=50026200"),
    ("Eiffel Scholarship",
     "https://www.campusfrance.org/en/france-excellence-eiffel-scholarship-program"),
    ("Fulbright Foreign Student Program",
     "https://foreign.fulbrightonline.org/about/foreign-student-program"),
    ("LPDP Beasiswa Perguruan Tinggi Utama Dunia (PTUD)",
     "https://lpdp.kemenkeu.go.id/en/beasiswa/umum/beasiswa-ptud/"),
    ("LPDP Beasiswa Reguler (Master)",
     "https://lpdp.kemenkeu.go.id/en/beasiswa/umum/beasiswa-reguler/"),
    ("LPDP Beasiswa Reguler (PhD)",
     "https://lpdp.kemenkeu.go.id/en/beasiswa/umum/beasiswa-reguler/"),
    ("MEXT Scholarship (University Recommendation)",
     "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/"),
    ("MEXT Scholarship for Japanese Studies Students",
     "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/"),
    ("MEXT Scholarship for Research Students",
     "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/"),
    ("MEXT Scholarship for Undergraduate Students",
     "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/"),
]

WORDING = re.compile(
    r"[^.\n]{0,160}(?:tuition|stipend|allowance|fully[- ]fund|full[- ]funding"
    r"|biaya Kuliah|beasiswa|dolar AS|uang saku|danaHt|airfare)[^.\n]{0,240}",
    re.IGNORECASE,
)


def _config(source_id, url: str):
    from services.ingestion.connectors.base_connector import ConnectorConfig

    return ConnectorConfig(
        source_id=source_id,
        url=url,
        timeout=30,
        user_agent="PolarisBot/0.3 (+V0.1 evidence capture; contact: research)",
    )


async def fetch_one(source_id, url: str):
    from services.ingestion.connectors.generic_connector import GenericHTTPConnector
    from services.ingestion.connectors.generic_playwright import (
        GenericPlaywrightConnector,
    )

    for label, factory in (
        ("http", lambda: GenericHTTPConnector(_config(source_id, url))),
        ("playwright", lambda: GenericPlaywrightConnector(_config(source_id, url))),
    ):
        connector = factory()
        try:
            await connector.connect()
            return label, await connector.fetch(url)
        except Exception:  # noqa: BLE001 — a refused fetch is a result
            continue
        finally:
            try:
                await connector.close()
            except Exception:  # noqa: BLE001
                pass
    return None, None


async def main() -> int:
    from services.ingestion.cleaner import clean
    from services.ingestion.loader import LoadedDocument
    from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
    from services.ingestion.repositories.raw_document_repository import (
        RawDocumentRepository,
    )

    session = SessionLocal()
    repo = RawDocumentRepository(session)
    mapper = RawDocumentMapper()
    try:
        for name, url in TARGETS:
            print("=" * 100)
            print(f"{name}\n  {url}")
            row = session.execute(
                text("SELECT source_id FROM scholarship WHERE scholarship_name = :n"),
                {"n": name},
            ).first()
            if row is None:
                print("  MISSING RECORD")
                continue
            source_id = row[0]

            how, result = await fetch_one(source_id, url)
            if result is None:
                print("  UNREACHABLE on this run")
                continue

            candidate = mapper.to_orm(result)
            candidate.source_id = source_id
            dup = repo.get_by_source_and_checksum(source_id, candidate.checksum)
            if dup is not None:
                doc_id = str(dup.document_id)
            else:
                doc_id = str(repo.save(candidate).document_id)
            session.commit()
            print(
                f"  OK via {how} status={result.status_code} "
                f"bytes={len(result.raw_content)} document={doc_id}"
            )

            cleaned = clean(
                LoadedDocument(
                    document_id="evidence",
                    source_id=str(source_id),
                    source_url=url,
                    content_type=result.content_type,
                    raw_content=result.raw_content,
                )
            )
            print(f"  title={cleaned.page_title!r}")
            seen: set[str] = set()
            for m in WORDING.finditer(cleaned.clean_text):
                line = " ".join(m.group(0).split())[:280]
                if line in seen:
                    continue
                seen.add(line)
                print("    | " + line)
                if len(seen) >= 14:
                    break
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
