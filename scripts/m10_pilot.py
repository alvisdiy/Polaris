"""M10 real-data pilot (M10.4 §16-§18).

Runs a small, controlled batch of *live* official pages through the whole
acquisition path and lands them in PENDING_REVIEW:

    official page
        → SafeFetch            (robots → URL/DNS → bounded retry → redirects)
        → RawDocument
        → cleaner              (invisible content stripped)
        → untrusted boundary
        → extraction
        → schema validation
        → quality gates
        → PENDING_REVIEW

Nothing is approved. Approval is a human decision and the pilot exists to
give that human something real to look at, so the script deliberately has no
code path that could take one.

    python scripts/m10_pilot.py --limit 10
    python scripts/m10_pilot.py --limit 10 --dry-run

``--dry-run`` performs the fetch and the extraction but writes nothing, which
is what to use when re-checking the pipeline against live sites without
touching the knowledge base.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database.models.raw_document import RawDocument  # noqa: E402
from database.models.scholarship_review_action import (  # noqa: E402
    ScholarshipReviewAction,
)
from database.models.source_registry import SourceRegistry  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.exploration.acquisition_service import AcquisitionService  # noqa: E402
from services.ingestion.connectors.generic_connector import (  # noqa: E402
    GenericHTTPConnector,
)
from services.ingestion.orchestrator import run_pipeline  # noqa: E402
from services.ingestion.real_extractor import DeterministicLLMClient  # noqa: E402
from services.ingestion.repositories.raw_document_mapper import (  # noqa: E402
    RawDocumentMapper,
)
from services.ingestion.repositories.raw_document_repository import (  # noqa: E402
    RawDocumentRepository,
)
from services.review import ReviewStatus  # noqa: E402


@dataclass
class PilotMetrics:
    """M10.4 §17, one counter per thing that can go wrong."""

    pages_attempted: int = 0
    pages_acquired: int = 0
    pages_failed: int = 0
    extraction_attempts: int = 0
    extraction_succeeded: int = 0
    schema_failures: int = 0
    quality_failures: int = 0
    unknown_deadline: int = 0
    unknown_degree: int = 0
    unknown_funding: int = 0
    conflicts: int = 0
    duplicates: int = 0
    candidate_revisions: int = 0
    human_corrections: int = 0
    approved: int = 0
    rejected: int = 0
    pending_review: int = 0
    failure_categories: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)

    def fail(self, category: str) -> None:
        self.failure_categories[category] = (
            self.failure_categories.get(category, 0) + 1
        )


def _official_urls(session, limit: int) -> list[tuple[SourceRegistry, str]]:
    """Verified official sources, most-recently fetched page from each.

    A pilot that re-fetches the same portal seven times measures the portal,
    not the pipeline, so this takes one page per source first and widens only
    if there are not enough sources to fill the batch.
    """
    rows = (
        session.query(SourceRegistry)
        .filter(SourceRegistry.status == "Active")
        .order_by(SourceRegistry.last_acquisition_at.desc().nullslast())
        .all()
    )
    chosen: list[tuple[SourceRegistry, str]] = []
    for source in rows:
        document = (
            session.query(RawDocument)
            .filter(RawDocument.source_id == source.source_id)
            .order_by(RawDocument.fetched_at.desc())
            .first()
        )
        if document is not None:
            chosen.append((source, document.source_url))
        if len(chosen) >= limit:
            break
    return chosen


async def _run(args) -> PilotMetrics:
    metrics = PilotMetrics()
    session = SessionLocal()
    raw_repo = RawDocumentRepository(session)
    raw_mapper = RawDocumentMapper()
    extractor = DeterministicLLMClient()
    acquisition = AcquisitionService(session)

    targets = _official_urls(session, args.limit)
    print(f"pilot: {len(targets)} official pages across {len({s.source_id for s, _ in targets})} sources")

    try:
        for source, url in targets:
            metrics.pages_attempted += 1
            connector = GenericHTTPConnector(
                _config(source.source_id, url)
            )
            try:
                fetch = await connector.fetch(url)
                metrics.pages_acquired += 1
            except Exception as exc:  # noqa: BLE001 — a refused fetch is a result
                metrics.pages_failed += 1
                metrics.fail(f"fetch: {type(exc).__name__}")
                print(f"  FETCH FAILED {url}: {exc}")
                continue

            document = raw_mapper.to_orm(fetch)
            existing = raw_repo.get_by_source_and_checksum(
                document.source_id, document.checksum
            )
            document = existing or raw_repo.save(document)

            metrics.extraction_attempts += 1
            result = run_pipeline(str(document.document_id), session, extractor)

            if result.raw_extraction.error:
                metrics.schema_failures += 1
                metrics.fail("schema: " + result.raw_extraction.error[:60])
                print(f"  SCHEMA  {url}: {result.raw_extraction.error[:90]}")
                continue
            if not result.is_valid:
                metrics.quality_failures += 1
                issues = "; ".join(i.message for i in result.validation_report.issues)
                metrics.fail("validation: " + issues[:60])
                print(f"  INVALID {url}: {issues[:120]}")
                continue

            metrics.extraction_succeeded += 1
            scholarship = result.raw_extraction.scholarship
            if scholarship.timeline.application_deadline is None:
                metrics.unknown_deadline += 1
            if scholarship.degree is None:
                metrics.unknown_degree += 1
            if scholarship.funding_type is None:
                metrics.unknown_funding += 1

            if args.dry_run:
                print(f"  DRY-RUN {url} -> {scholarship.scholarship_name!r}")
                metrics.rows.append(_row(url, scholarship, "dry-run"))
                continue

            saved = acquisition._persist_with_dedup(result, str(document.document_id))
            session.flush()
            if saved is None:
                metrics.duplicates += 1
                print(f"  DUPLICATE {url}: folded into an existing record")
                metrics.rows.append(_row(url, scholarship, "duplicate"))
                continue

            metrics.pending_review += 1
            metrics.rows.append(_row(url, scholarship, "persisted"))
            print(
                f"  PENDING  {url}\n"
                f"           name={saved.scholarship_name!r} "
                f"degree={saved.degree!r} funding={saved.funding_type!r}\n"
                f"           deadline={saved.timeline.application_deadline if saved.timeline else None} "
                f"blocking={(saved.quality_report or {}).get('blocking')}"
            )

        # The pilot's own audit: nothing it produced may be public.
        metrics.approved = _count(session, ReviewStatus.APPROVED, since=args.since)
        metrics.rejected = _count(session, ReviewStatus.REJECTED, since=args.since)
        metrics.candidate_revisions = session.execute(
            __import__("sqlalchemy").text("SELECT count(*) FROM scholarship_candidate_revision")
        ).scalar()
        metrics.human_corrections = session.execute(
            __import__("sqlalchemy").text(
                "SELECT count(*) FROM scholarship_review_action "
                "WHERE action IN ('corrected', 'candidate_approved')"
            )
        ).scalar()
        metrics.conflicts = session.execute(
            __import__("sqlalchemy").text(
                "SELECT count(*) FROM scholarship WHERE conflicts IS NOT NULL "
                "AND jsonb_array_length(conflicts) > 0"
            )
        ).scalar()
    finally:
        if not args.dry_run:
            session.commit()
        session.close()

    return metrics


def _config(source_id, url: str):
    from services.ingestion.connectors.base_connector import ConnectorConfig

    return ConnectorConfig(
        source_id=source_id,
        url=url,
        timeout=30,
        user_agent="PolarisBot/0.2 (+M10 pilot; contact: research)",
    )


def _row(url: str, scholarship, outcome: str) -> dict:
    return {
        "url": url,
        "outcome": outcome,
        "name": scholarship.scholarship_name,
        "provider": scholarship.provider_name,
        "degree": scholarship.degree,
        "funding_type": scholarship.funding_type,
        "deadline": scholarship.timeline.application_deadline,
        "unmapped_qualification": (scholarship.extraction_meta or {}).get(
            "unmapped_qualification"
        ),
        "source_url": (scholarship.extraction_meta or {}).get("source_url"),
        "looks_like_index": None,
    }


def _count(session, status: str, *, since=None) -> int:
    query = session.query(ScholarshipReviewAction).filter(
        ScholarshipReviewAction.new_state == status
    )
    if since:
        query = query.filter(ScholarshipReviewAction.occurred_at >= since)
    return query.count()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and extract without writing anything",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO timestamp; only count review actions after it",
    )
    args = parser.parse_args()
    if args.since is None:
        args.since = datetime.now(timezone.utc)

    metrics = asyncio.run(_run(args))
    payload = {k: v for k, v in metrics.__dict__.items() if k != "rows"}
    print(json.dumps(payload, indent=2, default=str))
    print("\nrows:")
    for row in metrics.rows:
        print(json.dumps(row, default=str))


if __name__ == "__main__":
    main()
