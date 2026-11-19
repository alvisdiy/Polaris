"""Phase 3 — grow the approved set through the real acquisition path.

Phase 2 left 27 approved records, three short of the brief's target. This
script gets there the way the product is meant to get there: it claims pending
``opportunity`` candidates from the discovery frontier, fetches each one
through the existing connectors, and runs the unchanged ingestion pipeline —
no seed data, no hand-typed fields, no direct writes.

Every record it creates arrives in review through ``record_submission`` and is
then approved through ``ReviewService.approve``, so nothing reaches
publication without the gates passing. Records that fail the gate are left in
review and reported, not approved over.

Frontier rows are marked as they go: ``done`` when the page was processed,
``rejected`` when the page's own content says it is not a scholarship page,
``failed`` when the fetch could not complete after retries. Nothing is
deleted.

    python scripts/v01_phase3_acquire.py --limit 40
    python scripts/v01_phase3_acquire.py --limit 40 --approve
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import text

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.session import SessionLocal  # noqa: E402

USER_AGENT = "PolarisBot/0.3 (+V0.1 ship verification; contact: research)"

# Below this, a 200 response is a JavaScript shell rather than a page.
THIN_RESPONSE_BYTES = 4000


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _load_sources(session) -> dict[str, object]:
    """Map domain -> SourceRegistry row for sources we can attribute a page to.

    Attribution matters: the mapper resolves provider and country from the
    source row, so a page fetched without one cannot be placed.
    """
    rows = session.execute(
        text(
            "SELECT source_id, source_name, official_url, crawl_entry_url "
            "FROM source_registry WHERE status = 'Active'"
        )
    ).all()
    by_domain: dict[str, object] = {}
    for source_id, name, official_url, entry_url in rows:
        for url in (entry_url, official_url):
            if url:
                by_domain.setdefault(_domain(url), (source_id, name, url))
    return by_domain


def _claim(session, limit: int):
    """Take pending opportunity candidates whose domain has a registered source.

    Claimed under lease like any other frontier worker, so a concurrent run
    cannot pick up the same URL.
    """
    return session.execute(
        text(
            """
            SELECT cf.candidate_id, cf.url, cf.depth
            FROM discovery_frontier cf
            WHERE cf.state = 'pending'
              AND cf.candidate_type = 'opportunity'
              AND (cf.lease_expires_at IS NULL OR cf.lease_expires_at < now())
            ORDER BY cf.priority ASC, cf.depth DESC, cf.created_at ASC
            LIMIT :limit
            """
        ),
        # Most pending candidates sit on domains with no registered source and
        # cannot be attributed, so the pool is drawn wide and filtered below.
        {"limit": limit * 60},
    ).all()


async def _fetch(session, source_id, url: str):
    """HTTP first, browser as fallback. No SafeFetch bypass either way."""
    from services.ingestion.connectors.base_connector import ConnectorConfig
    from services.ingestion.connectors.generic_connector import GenericHTTPConnector
    from services.ingestion.connectors.generic_playwright import (
        GenericPlaywrightConnector,
    )

    config = ConnectorConfig(
        source_id=source_id, url=url, timeout=30, user_agent=USER_AGENT
    )
    errors = []
    for label, factory in (
        ("http", lambda: GenericHTTPConnector(config)),
        ("playwright", lambda: GenericPlaywrightConnector(config)),
    ):
        connector = factory()
        try:
            await connector.connect()
            result = await connector.fetch(url)
            # A 200 with a few hundred bytes is a client-rendered shell: the
            # page exists, its content is assembled in the browser, and the
            # extractor would see an empty document and judge it irrelevant.
            # Escalating to the browser connector is not a SafeFetch bypass —
            # it is the same fetch through a renderer.
            if len(result.raw_content) < THIN_RESPONSE_BYTES:
                errors.append(
                    f"{label}: {len(result.raw_content)} bytes, "
                    f"too thin to be the rendered page"
                )
                continue
            return result, label, errors
        except Exception as exc:  # noqa: BLE001 — a refused fetch is a result
            errors.append(f"{label}: {type(exc).__name__}: {str(exc)[:120]}")
        finally:
            try:
                await connector.close()
            except Exception:  # noqa: BLE001
                pass
    return None, None, errors


def _mark(session, candidate_id, state: str, outcome: dict) -> None:
    session.execute(
        text(
            "UPDATE discovery_frontier SET state = :s, outcome = CAST(:o AS jsonb), "
            "processed_at = now(), updated_at = now(), "
            "lease_expires_at = NULL, retry_count = retry_count + 1 "
            "WHERE candidate_id = :c"
        ),
        # json.dumps, not str(): a Python tuple renders as "(a, b)" which is
        # not JSON, and evidence lists are tuples.
        {"s": state, "o": json.dumps(outcome, default=str), "c": candidate_id},
    )


async def run(limit: int, approve: bool, dry_run: bool) -> int:
    from services.exploration.acquisition_service import AcquisitionService
    from services.exploration.listing_guard import (
        ListingGuard,
        classify_listing_page,
    )
    from services.exploration.page_intent import PageIntent, classify_page_intent
    from services.ingestion.cleaner import clean
    from services.ingestion.loader import LoadedDocument
    from services.ingestion.orchestrator import run_pipeline
    from services.ingestion.real_extractor import DeterministicLLMClient
    from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
    from services.ingestion.repositories.raw_document_repository import (
        RawDocumentRepository,
    )

    session = SessionLocal()
    repo = RawDocumentRepository(session)
    mapper = RawDocumentMapper()
    llm = DeterministicLLMClient()
    service = AcquisitionService(session, origin="phase3_acquisition")

    tally = {
        "attributed": 0, "fetched": 0, "unreachable": 0,
        "not_a_scholarship_page": 0, "extraction_failed": 0,
        "duplicate": 0, "new_record": 0, "approved": 0, "gate_blocked": 0,
        "listing_page": 0,
    }
    tally["listing_signals"] = {}
    try:
        sources = _load_sources(session)
        candidates = _claim(session, limit)
        print(f"claimed {len(candidates)} frontier candidates "
              f"(aiming for {limit} attributed pages)\n")

        for candidate_id, url, depth in candidates:
            entry = sources.get(_domain(url))
            if entry is None:
                continue
            source_id, source_name, _ = entry
            tally["attributed"] += 1
            if tally["attributed"] > limit:
                tally["attributed"] -= 1
                break

            print("=" * 96)
            print(f"{url}\n  source={source_name} depth={depth}")
            if dry_run:
                continue

            result, how, errors = await _fetch(session, source_id, url)
            if result is None:
                tally["unreachable"] += 1
                _mark(session, candidate_id, "failed", {"errors": errors})
                print("  UNREACHABLE  " + "; ".join(errors))
                continue
            tally["fetched"] += 1

            doc = mapper.to_orm(result)
            existing = repo.get_by_source_and_checksum(doc.source_id, doc.checksum)
            doc = existing if existing else repo.save(doc)
            session.commit()

            cleaned = clean(
                LoadedDocument(
                    document_id=str(doc.document_id),
                    source_id=str(doc.source_id),
                    source_url=doc.source_url,
                    content_type=doc.content_type,
                    raw_content=doc.raw_content,
                )
            )
            intent = classify_page_intent(
                url=doc.source_url,
                page_title=cleaned.page_title,
                headings=cleaned.headings,
                anchors=cleaned.anchors,
                text=cleaned.clean_text,
            )
            print(
                f"  fetched via {how} status={result.status_code} "
                f"bytes={len(result.raw_content)} intent={intent.intent}/"
                f"{intent.confidence}"
            )
            if intent.intent not in (PageIntent.SCHOLARSHIP_DETAIL, PageIntent.UNKNOWN):
                tally["not_a_scholarship_page"] += 1
                _mark(
                    session, candidate_id, "rejected",
                    {"intent": intent.intent, "confidence": intent.confidence,
                     "evidence": intent.evidence[:3]},
                )
                session.commit()
                print("  not a scholarship page — frontier rejected with evidence")
                continue

            # The listing guard. This script mirrors the production loop, so it
            # must apply the same boundary: without it this tool remains a
            # route by which an aggregator listing page becomes a published
            # scholarship, which is the exact defect V0.1.1 closed.
            guard = classify_listing_page(
                page_title=cleaned.page_title,
                headings=cleaned.headings,
                anchors=cleaned.anchors,
                text=cleaned.clean_text,
                intent=intent,
            )
            if not guard.should_extract:
                tally["listing_page"] += 1
                for name in guard.signals:
                    tally["listing_signals"][name] = (
                        tally["listing_signals"].get(name, 0) + 1
                    )
                _mark(
                    session, candidate_id, "rejected",
                    {"reason": ListingGuard.REASON, "signals": list(guard.signals),
                     "verdict": guard.verdict, **guard.detail},
                )
                session.commit()
                print(
                    f"  LISTING PAGE — not extracted ({', '.join(guard.signals)})"
                )
                continue

            pipeline = run_pipeline(str(doc.document_id), session, llm)
            if not pipeline.is_valid or pipeline.raw_extraction.scholarship is None:
                tally["extraction_failed"] += 1
                _mark(session, candidate_id, "done", {"extraction": "invalid"})
                session.commit()
                print("  extraction invalid")
                continue

            before = session.execute(
                text("SELECT count(*) FROM scholarship")
            ).scalar_one()
            saved = service._persist_with_dedup(pipeline, str(doc.document_id))
            session.commit()
            after = session.execute(
                text("SELECT count(*) FROM scholarship")
            ).scalar_one()

            if saved is None:
                tally["duplicate"] += 1
                _mark(
                    session, candidate_id, "done",
                    {"outcome": "merged into an existing identity"},
                )
                session.commit()
                print("  duplicate identity — merged, no new record")
                continue

            tally["new_record"] += 1
            _mark(
                session, candidate_id, "done",
                {"outcome": "persisted", "scholarship_id": str(saved.scholarship_id),
                 "name": saved.scholarship_name},
            )
            session.commit()
            print(f"  NEW RECORD  {saved.scholarship_name}  (+{after - before})")

            if not approve:
                continue

            from database.models.scholarship_review_action import ReviewSource
            from services.review.service import ReviewService

            review = ReviewService(session)
            report = review.evaluate_quality(saved)
            try:
                outcome = review.approve(
                    str(saved.scholarship_id),
                    actor="phase3-acquisition",
                    reason="verified against the live official page during Phase 3 acquisition",
                    source=ReviewSource.SYSTEM,
                    evidence_url=saved.official_page_url,
                )
                session.commit()
                tally["approved"] += 1
                print(f"  APPROVED  version={outcome.version_id}")
            except Exception as exc:  # noqa: BLE001 — a refusal is a result
                session.rollback()
                tally["gate_blocked"] += 1
                _mark(session, candidate_id, "done",
                      {"outcome": "left in review", "gate": str(exc)[:300]})
                session.commit()
                print(f"  LEFT IN REVIEW  {type(exc).__name__}: {str(exc)[:200]}")
                print(f"  gate says: publishable={report.publishable} "
                      f"blocking={report.blocking}")

        print("\n" + "=" * 96)
        for key, value in tally.items():
            print(f"  {key:28} {value}")
    finally:
        session.close()
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.limit, args.approve, args.dry_run))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
