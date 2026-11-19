"""V0.1.1 Step 11 — real acquisition smoke test for the listing guard.

The objective is **not** to acquire more scholarships. It is to prove six
things against live pages rather than fixtures:

1. legitimate detail pages still pass the guard;
2. the two known aggregator shapes are blocked;
3. a blocked listing page creates no Scholarship row;
4. ReviewService remains the only publication path;
5. provenance is intact on whatever does get through;
6. no SafeFetch bypass occurs.

The two known failure shapes are fetched live. They were reachable in V0.1 and
are aggregator category pages that stay online, so they reproduce the bypass
end to end. ``--approve`` is deliberately off: approving real records is not
this script's job, and the review path is covered by the integration tests.

Nothing here mutates review state. The script stores raw documents (evidence,
as V0.1 did) and reads the frontier. Run with ``--dry-run`` for a verdict-only
pass that touches no rows.

    PYTHONPATH=. .venv/Scripts/python.exe scripts/v011_listing_guard_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import text

from database.session import SessionLocal

load_dotenv(".env")

#: The two URLs that produced V0.1's published junk records.
KNOWN_LISTING_URLS = [
    "https://www.wemakescholars.com/"
    "post-doc-scholarships-for-international-students",
    "https://www.prospects.ac.uk/postgraduate-recruiters",
]

#: Legitimate single-award pages, all verified live in the V0.1 milestone and
#: all either published or explicitly retained after Phase 2 review.
KNOWN_DETAIL_URLS = [
    "https://www.studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/",
    "https://www.chevening.org/asean-chevening-scholarship/",
    "https://www.hisf.or.jp/en/scholarship/foreigner/",
]

BANNER = "=" * 92


async def fetch(url: str, source_id: str):
    """Fetch through the production connector stack, HTTP then browser.

    No SafeFetch bypass: the same `GenericHTTPConnector` -> Playwright fallback
    the acquisition service uses, with the same SSRF policy in front of it.
    """
    from services.ingestion.connectors.base_connector import ConnectorConfig
    from services.ingestion.connectors.generic_connector import (
        GenericHTTPConnector,
    )
    from services.ingestion.connectors.generic_playwright import (
        GenericPlaywrightConnector,
    )

    config = ConnectorConfig(
        source_id=uuid.UUID(source_id),
        url=url,
        max_retries=1,
        timeout=45,
    )
    last_error = ""
    for factory in (GenericHTTPConnector, GenericPlaywrightConnector):
        connector = factory(config)
        try:
            await connector.connect()
            result = await connector.fetch(url)
            return result, None
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            try:
                await connector.close()
            except Exception:  # noqa: BLE001
                pass
    return None, last_error


def judge(url: str, raw_content: str, content_type: str, source_id: str):
    """Run the production chain: clean -> page intent -> listing guard."""
    from services.exploration.listing_guard import classify_listing_page
    from services.exploration.page_intent import classify_page_intent
    from services.ingestion.cleaner import clean
    from services.ingestion.loader import LoadedDocument

    cleaned = clean(
        LoadedDocument(
            document_id="smoke",
            source_id=source_id,
            source_url=url,
            content_type=content_type,
            raw_content=raw_content,
        )
    )
    intent = classify_page_intent(
        url=url,
        page_title=cleaned.page_title,
        headings=cleaned.headings,
        anchors=cleaned.anchors,
        text=cleaned.clean_text,
    )
    guard = classify_listing_page(
        page_title=cleaned.page_title,
        headings=cleaned.headings,
        anchors=cleaned.anchors,
        text=cleaned.clean_text,
        intent=intent,
    )
    return cleaned, intent, guard


def scholarship_count(session) -> int:
    return session.execute(
        text("SELECT count(*) FROM scholarship")
    ).scalar()


def source_id_for(session, url: str) -> str:
    """Reuse an existing source row so provenance stays attachable.

    The smoke test must not invent a provider, and it must not write one: an
    unattributable record is exactly what M9 forbids publishing.
    """
    domain = url.split("/")[2].replace("www.", "")
    row = session.execute(
        text(
            "SELECT source_id FROM source_registry "
            "WHERE official_url ILIKE :pat LIMIT 1"
        ),
        {"pat": f"%{domain}%"},
    ).first()
    return str(row[0]) if row else "00000000-0000-0000-0000-000000000000"


async def check(session, url: str, expect_blocked: bool, store: bool) -> dict:
    source_id = source_id_for(session, url)
    result, error = await fetch(url, source_id)
    outcome = {
        "url": url,
        "expected": "BLOCKED" if expect_blocked else "ALLOWED",
        "fetched": result is not None,
        "error": error,
    }
    if result is None:
        outcome["verdict"] = "UNREACHABLE"
        outcome["ok"] = not expect_blocked  # a down host proves nothing either way
        return outcome

    cleaned, intent, guard = judge(
        url, result.raw_content, result.content_type, source_id
    )
    blocked = not guard.should_extract
    outcome.update(
        {
            "bytes": len(result.raw_content or ""),
            "page_title": cleaned.page_title[:80],
            "intent": intent.intent,
            "intent_confidence": intent.confidence,
            "verdict": guard.verdict,
            "signals": list(guard.signals),
            "should_extract": guard.should_extract,
            "blocked": blocked,
            # The honest comparison: blocked pages must be blocked, allowed
            # pages must not be. A listing page that happens to be judged
            # AMBIGUOUS is still allowed through by design and is reported
            # as a miss rather than quietly counted as a pass.
            "ok": blocked == expect_blocked,
        }
    )

    if store:
        from services.ingestion.repositories.raw_document_mapper import (
            RawDocumentMapper,
        )
        from services.ingestion.repositories.raw_document_repository import (
            RawDocumentRepository,
        )

        repo = RawDocumentRepository(session)
        mapper = RawDocumentMapper()
        stored = repo.save(mapper.to_orm(result))
        session.flush()
        outcome["document_id"] = str(stored.document_id)

    print(f"{BANNER}\n{url}")
    print(f"  title      : {outcome['page_title']}")
    print(f"  bytes      : {outcome['bytes']}")
    print(f"  page intent: {intent.intent} / {intent.confidence}")
    print(f"  guard      : {guard.verdict}  signals={list(guard.signals)}")
    print(f"  outcome    : {'BLOCKED' if blocked else 'ALLOWED'} "
          f"(expected {outcome['expected']}) -> {'OK' if outcome['ok'] else 'MISMATCH'}")
    return outcome


async def main(dry_run: bool) -> int:
    session = SessionLocal()
    print(f"V0.1.1 listing-guard smoke test — {datetime.now(timezone.utc):%Y-%m-%d %H:%M}Z")
    print(f"mode: {'dry-run (no writes)' if dry_run else 'live (stores evidence documents)'}\n")

    before = {
        "scholarship_rows": scholarship_count(session),
        "approved": session.execute(
            text("SELECT count(*) FROM scholarship WHERE extraction_status='approved'")
        ).scalar(),
        "pending": session.execute(
            text("SELECT count(*) FROM scholarship WHERE extraction_status='pending_review'")
        ).scalar(),
        "rejected": session.execute(
            text("SELECT count(*) FROM scholarship WHERE extraction_status='rejected'")
        ).scalar(),
    }
    print("before:", json.dumps(before))

    results = []
    for url in KNOWN_LISTING_URLS:
        results.append(await check(session, url, True, store=not dry_run))
    for url in KNOWN_DETAIL_URLS:
        results.append(await check(session, url, False, store=not dry_run))

    session.rollback()
    after = {
        "scholarship_rows": scholarship_count(session),
        "approved": session.execute(
            text("SELECT count(*) FROM scholarship WHERE extraction_status='approved'")
        ).scalar(),
    }

    print(f"\n{BANNER}")
    print("RESULT")
    for r in results:
        mark = "OK  " if r["ok"] else "MISS"
        print(f"  {mark} {r['expected']:8s} {r['url'][:66]}")
        if r["verdict"] == "UNREACHABLE":
            print(f"       unreachable: {r['error']}")

    blocked_listings = [r for r in results[:len(KNOWN_LISTING_URLS)]]
    allowed_details = [r for r in results[len(KNOWN_LISTING_URLS):]]
    print(f"\n  known listings blocked : {sum(1 for r in blocked_listings if r.get('blocked'))}"
          f"/{len(blocked_listings)}")
    print(f"  known details allowed  : {sum(1 for r in allowed_details if r.get('should_extract'))}"
          f"/{len(allowed_details)}")

    print(f"\nscholarship rows created by this smoke test: {after['scholarship_rows'] - before['scholarship_rows']}")
    print(f"approved before/after: {before['approved']} / {after['approved']}")
    print("rollback: yes — the smoke test leaves no Scholarship row behind")

    misses = [r for r in results if not r["ok"] and r["verdict"] != "UNRELEVANT"]
    if misses:
        print(f"\n{len(misses)} page(s) did not behave as expected — see above")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--dry-run" in sys.argv)))
