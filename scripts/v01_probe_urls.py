"""Probe candidate replacement official URLs for the legacy approved records.

Phase 2A found every legacy record's stored official_page_url is dead or
bot-blocked. This asks a narrower question: does a *live* official page exist
for each programme, and can SafeFetch reach it? It fetches through the
existing connectors only — no bypass — and reports status, page intent and
what the extractor makes of the page.

    python scripts/v01_probe_urls.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.session import SessionLocal  # noqa: E402

# (scholarship_name, candidate official url). Candidates come from the
# providers' own current sites, found via web search; nothing here bypasses
# SafeFetch, and a candidate that will not fetch is simply not used.
CANDIDATES = [
    ("Chinese Government Scholarship", "https://www.csc.edu.cn/"),
    ("Chinese Government Scholarship", "https://studyinchina.csc.edu.cn/"),
    ("Chinese Government Scholarship",
     "https://us.china-embassy.gov.cn/eng/lxfw/studyinchina/chinesegovernmentscholarship/"),
]


def _config(source_id, url: str):
    from services.ingestion.connectors.base_connector import ConnectorConfig

    return ConnectorConfig(
        source_id=source_id,
        url=url,
        timeout=30,
        user_agent="PolarisBot/0.3 (+V0.1 legacy verification; contact: research)",
    )


async def probe(session, name: str, url: str) -> None:
    from services.exploration.page_intent import classify_page_intent
    from services.ingestion.cleaner import clean
    from services.ingestion.connectors.generic_connector import GenericHTTPConnector
    from services.ingestion.connectors.generic_playwright import (
        GenericPlaywrightConnector,
    )
    from services.ingestion.loader import LoadedDocument
    from services.ingestion.real_extractor import DeterministicLLMClient

    row = session.execute(
        text("SELECT source_id FROM scholarship WHERE scholarship_name = :n"),
        {"n": name},
    ).first()
    if row is None:
        print(f"MISSING RECORD {name}")
        return
    source_id = row[0]

    fetch = None
    how = ""
    for label, factory in (
        ("http", lambda: GenericHTTPConnector(_config(source_id, url))),
        ("playwright", lambda: GenericPlaywrightConnector(_config(source_id, url))),
    ):
        connector = factory()
        try:
            # The browser connector needs an explicit session before fetch;
            # without it every fetch raises "Not connected".
            await connector.connect()
            fetch = await connector.fetch(url)
            how = label
            break
        except Exception as exc:  # noqa: BLE001 — a refused fetch is a result
            print(f"  {label} failed: {type(exc).__name__}: {str(exc)[:120]}")
        finally:
            try:
                await connector.close()
            except Exception:  # noqa: BLE001
                pass

    if fetch is None:
        print(f"UNREACHABLE  {name}\n  {url}\n")
        return

    cleaned = clean(
        LoadedDocument(
            document_id="probe",
            source_id=str(source_id),
            source_url=url,
            content_type=fetch.content_type,
            raw_content=fetch.raw_content,
        )
    )
    intent = classify_page_intent(
        url=url,
        page_title=cleaned.page_title,
        headings=cleaned.headings,
        anchors=cleaned.anchors,
        text=cleaned.clean_text,
    )
    payload = DeterministicLLMClient().extract_scholarship(
        clean_text=cleaned.clean_text,
        source_url=url,
        page_title=cleaned.page_title,
        headings=tuple(cleaned.headings),
        anchors=tuple(cleaned.anchors),
        looks_like_index=cleaned.looks_like_index,
    )
    payload.pop("_extraction", None)
    print(f"OK via {how}  {name}  (status={fetch.status_code} bytes={len(fetch.raw_content)})")
    print(f"  {url}")
    print(f"  title={cleaned.page_title!r} intent={intent.intent}/{intent.confidence}")
    print(
        f"  extracted name={payload.get('scholarship_name')!r} "
        f"degree={payload.get('degree')!r} funding={payload.get('funding_type')!r}"
    )
    print()


async def main() -> int:
    session = SessionLocal()
    try:
        for name, url in CANDIDATES:
            print("=" * 100)
            await probe(session, name, url)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
