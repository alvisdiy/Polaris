"""AcquisitionService — frontier-aware scholarship acquisition.

Reuses the existing pipeline untouched:
  fetch → RawDocument → cleaner → extractor (DeterministicLLMClient) →
  validator → Scholarship persistence

Adds: scholarship identity dedup (one canonical Scholarship per
provider+name+country, regardless of how many sites published it) and
provenance recording.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import func

from services.exploration.candidate_analyzer import CandidateAnalyzer
from services.scholarship.freshness import classify_deadline

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from database.models.source_registry import SourceRegistry


def scholarship_identity_key(provider_id, name: str, country_id) -> str:
    normalized = re.sub(r"\s+", " ", (name or "").strip().lower())
    return hashlib.sha256(f"{provider_id}|{normalized}|{country_id}".encode("utf-8")).hexdigest()


@dataclass
class AcquisitionMetrics:
    scholarship_urls_found: int = 0
    pages_fetched: int = 0
    extraction_succeeded: int = 0
    extraction_failed: int = 0
    scholarships_persisted: int = 0
    duplicates_collapsed: int = 0
    errors: list[str] = field(default_factory=list)


class AcquisitionService:
    """Feeds verified sources into the existing extraction pipeline."""

    def __init__(self, session: "Session", analyzer: CandidateAnalyzer | None = None) -> None:
        self.session = session
        self.analyzer = analyzer or CandidateAnalyzer()

    async def acquire_from_source(self, source: "SourceRegistry", max_pages: int = 10) -> AcquisitionMetrics:
        """Discover scholarship URLs on a verified source and run the pipeline."""
        metrics = AcquisitionMetrics()

        from services.ingestion.connectors.base_connector import ConnectorConfig
        from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector
        from services.ingestion.orchestrator import persist_scholarship, run_pipeline
        from services.ingestion.real_extractor import DeterministicLLMClient
        from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
        from services.ingestion.repositories.raw_document_repository import RawDocumentRepository

        config = ConnectorConfig(
            source_id=source.source_id,
            url=source.crawl_entry_url or source.official_url,
            timeout=30,
            user_agent="PolarisBot/0.2 (+discovery research)",
        )
        connector = GenericPlaywrightConnector(config)
        llm_client = DeterministicLLMClient()
        raw_repo = RawDocumentRepository(self.session)
        mapper = RawDocumentMapper()

        try:
            await connector.connect()
            candidate_urls = await connector.discover()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Acquisition discovery failed for {}: {}", source.source_id, exc)
            metrics.errors.append(f"discover: {exc}")
            await connector.close()
            return metrics

        metrics.scholarship_urls_found = len(candidate_urls)

        for url in candidate_urls[:max_pages]:
            try:
                fetch_result = await connector.fetch(url)
                metrics.pages_fetched += 1
                raw_doc = mapper.to_orm(fetch_result)

                existing = raw_repo.get_by_source_and_checksum(raw_doc.source_id, raw_doc.checksum)
                if existing:
                    raw_doc = existing
                else:
                    raw_doc = raw_repo.save(raw_doc)

                result = run_pipeline(str(raw_doc.document_id), self.session, llm_client)
                if not result.is_valid or result.raw_extraction.scholarship is None:
                    metrics.extraction_failed += 1
                    continue

                metrics.extraction_succeeded += 1
                persisted = self._persist_with_dedup(result, str(raw_doc.document_id))
                if persisted:
                    metrics.scholarships_persisted += 1
                else:
                    metrics.duplicates_collapsed += 1
            except Exception as exc:  # noqa: BLE001
                metrics.errors.append(f"{url}: {exc}"[:300])
                logger.debug("Acquisition failed for {}: {}", url, exc)

        try:
            await connector.close()
        except Exception:  # noqa: BLE001
            pass

        return metrics

    # ------------------------------------------------------------------

    def _persist_with_dedup(self, result, document_id: str):
        """Persist through the existing mapper/repository with identity dedup."""
        from services.ingestion.repositories.raw_document_repository import RawDocumentRepository

        raw_doc = RawDocumentRepository(self.session).get_by_id(document_id)
        if raw_doc is None:
            return None

        from services.scholarship import ScholarshipMapper

        mapper = ScholarshipMapper(self.session)
        try:
            scholarship = mapper.to_orm(
                extracted=result.raw_extraction.scholarship,
                source_id=str(raw_doc.source_id),
            )
        except ValueError as exc:
            # Missing provider/country references — extraction can't be placed.
            logger.debug("Mapping failed for doc {}: {}", document_id, exc)
            return None

        scholarship.identity_key = scholarship_identity_key(
            scholarship.provider_id, scholarship.scholarship_name, scholarship.country_id
        )

        from database.models.scholarship import Scholarship

        existing = (
            self.session.query(Scholarship)
            .filter(Scholarship.identity_key == scholarship.identity_key)
            .first()
        )
        if existing is not None:
            # One canonical row per identity: a re-discovery refreshes freshness
            # and provenance instead of creating a duplicate opportunity.
            self._merge_reacquisition(existing, scholarship, raw_doc.raw_content or "")
            return None

        page_text = raw_doc.raw_content or ""
        scholarship.deadline_state = classify_deadline(
            scholarship.timeline.application_deadline if scholarship.timeline else None,
            page_text=page_text,
        )

        from services.scholarship.repository import ScholarshipRepository

        return ScholarshipRepository(self.session).save(scholarship)

    def _merge_reacquisition(self, existing, fresh, page_text: str) -> None:
        """Fold a re-discovery into the canonical scholarship row.

        - A freshly parsed deadline/cycle wins over the stored one (the official
          source's current cycle is the truth; an old cycle must not survive).
        - deadline_state is recomputed from the resulting timeline — an expired
          record that still looks fine in the DB gets corrected here.
        - The observation itself is recorded as an append-only version row so
          provenance accumulates without unbounded JSON growth.
        """
        from database.models.scholarship_version import ScholarshipVersion

        fresh_tl = fresh.timeline
        new_deadline = fresh_tl.application_deadline if fresh_tl else None
        new_cycle = fresh_tl.application_cycle if fresh_tl else None

        if existing.timeline is not None:
            if new_deadline:
                existing.timeline.application_deadline = new_deadline
            if new_cycle:
                existing.timeline.application_cycle = new_cycle
            effective_deadline = existing.timeline.application_deadline
        else:
            effective_deadline = new_deadline

        state = classify_deadline(effective_deadline, page_text=page_text)
        existing.deadline_state = state
        existing.last_verified_at = datetime.now(timezone.utc)

        last_no = (
            self.session.query(func.max(ScholarshipVersion.version_number))
            .filter(ScholarshipVersion.scholarship_id == existing.scholarship_id)
            .scalar()
        )
        self.session.add(
            ScholarshipVersion(
                scholarship_id=existing.scholarship_id,
                version_number=(last_no or 0) + 1,
                changed_at=datetime.now(timezone.utc),
                source_url=(fresh.official_page_url or None),
                change_summary=f"reacquired; deadline_state={state}; deadline={effective_deadline or 'none'}",
            )
        )
        self.session.flush()
