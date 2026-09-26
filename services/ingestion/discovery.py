"""Orchestrate scholarship discovery from official sources.

Discovery flow:
1. Connect to source
2. Discover candidate URLs
3. Filter and dedupe URLs
4. Fetch each page
5. Process through extraction pipeline
6. Persist valid scholarships
7. Report metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from loguru import logger

from services.ingestion.connectors.base_connector import BaseConnector, ConnectorConfig
from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
from services.ingestion.repositories.raw_document_repository import RawDocumentRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class DiscoveryMetrics:
    """Track discovery and processing outcomes."""

    source_id: UUID
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    candidate_urls_found: int = 0
    urls_after_filter: int = 0
    urls_already_seen: int = 0
    fetch_succeeded: int = 0
    fetch_failed: int = 0
    extraction_succeeded: int = 0
    extraction_failed: int = 0
    persisted: int = 0
    duplicates_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_id": str(self.source_id),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "candidate_urls_found": self.candidate_urls_found,
            "urls_after_filter": self.urls_after_filter,
            "urls_already_seen": self.urls_already_seen,
            "fetch_succeeded": self.fetch_succeeded,
            "fetch_failed": self.fetch_failed,
            "extraction_succeeded": self.extraction_succeeded,
            "extraction_failed": self.extraction_failed,
            "persisted": self.persisted,
            "duplicates_skipped": self.duplicates_skipped,
            "errors": self.errors,
        }


@dataclass
class DiscoveredURL:
    """A candidate URL discovered from a source."""

    url: str
    source_id: UUID
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DiscoveryOrchestrator:
    """Orchestrates scholarship discovery from a single source."""

    def __init__(self, connector: BaseConnector, session: Session) -> None:
        self.connector = connector
        self.session = session
        self.metrics = DiscoveryMetrics(source_id=connector.config.source_id)
        self._raw_doc_repo = RawDocumentRepository(session)
        self._raw_doc_mapper = RawDocumentMapper()

    async def discover_and_process(
        self,
        url_filter: callable[[str], bool] | None = None,
        max_urls: int = 50,
    ) -> DiscoveryMetrics:
        """Run the full discovery and processing pipeline.

        Args:
            url_filter: Optional function to filter candidate URLs.
                       Return True to keep URL, False to reject.
            max_urls: Maximum number of URLs to process in one run.

        Returns:
            DiscoveryMetrics with counts and errors.
        """
        logger.info(
            "Starting discovery for source_id={}",
            self.connector.config.source_id,
        )

        try:
            # 1. Discover candidate URLs
            candidate_urls = await self.connector.discover()
            self.metrics.candidate_urls_found = len(candidate_urls)
            logger.info("Discovered {} candidate URLs", len(candidate_urls))

            if not candidate_urls:
                logger.info("No candidate URLs found")
                return self._finalize()

            # 2. Apply optional filter
            if url_filter:
                candidate_urls = [u for u in candidate_urls if url_filter(u)]
            self.metrics.urls_after_filter = len(candidate_urls)

            # 3. Limit URLs per run
            if len(candidate_urls) > max_urls:
                logger.info("Limiting to {} URLs (from {})", max_urls, len(candidate_urls))
                candidate_urls = candidate_urls[:max_urls]

            # 4. Check for already-seen URLs (URL-level dedup)
            seen_urls = self._get_seen_urls(candidate_urls)
            new_urls = [u for u in candidate_urls if u not in seen_urls]
            self.metrics.urls_already_seen = len(seen_urls.intersection(candidate_urls))
            logger.info(
                "{} new URLs to process ({} already seen)",
                len(new_urls),
                self.metrics.urls_already_seen,
            )

            # 5. Fetch and process each URL
            for url in new_urls:
                try:
                    await self._process_single_url(url)
                except Exception as e:
                    logger.error("Error processing {}: {}", url, e)
                    self.metrics.errors.append(f"{url}: {e}")
                    self.metrics.fetch_failed += 1

            # 6. Reprocess pending RawDocuments (extraction may have failed in prior runs)
            await self._reprocess_pending_documents()

            return self._finalize()

        except Exception as e:
            logger.exception("Discovery failed: {}", e)
            self.metrics.errors.append(str(e))
            return self._finalize()

    async def _process_single_url(self, url: str) -> None:
        """Fetch and process a single discovered URL."""
        from services.ingestion.orchestrator import run_pipeline
        from services.ingestion.real_extractor import DeterministicLLMClient

        try:
            # Fetch the URL
            fetch_result = await self.connector.fetch(url)
            self.metrics.fetch_succeeded += 1

            # Map to RawDocument
            raw_doc = self._raw_doc_mapper.to_orm(fetch_result)

            # Check for duplicate by checksum
            existing = self._raw_doc_repo.get_by_source_and_checksum(
                raw_doc.source_id, raw_doc.checksum
            )
            if existing:
                logger.info("Duplicate document (checksum match): {}", url)
                self.metrics.duplicates_skipped += 1
                return

            # Save new document
            saved = self._raw_doc_repo.save(raw_doc)
            logger.info("Saved RawDocument: {} from {}", saved.document_id, url)

            # Run extraction pipeline
            llm_client = DeterministicLLMClient()
            result = run_pipeline(str(saved.document_id), self.session, llm_client)

            if result.is_valid:
                from services.ingestion.orchestrator import persist_scholarship
                persisted = persist_scholarship(result, str(saved.document_id), self.session)
                if persisted:
                    self.metrics.extraction_succeeded += 1
                    self.metrics.persisted += 1
                    logger.info("Extraction and persistence succeeded for {}", url)
                else:
                    self.metrics.extraction_failed += 1
                    logger.warning("Persistence failed for valid result {}", url)
            else:
                self.metrics.extraction_failed += 1
                logger.warning("Extraction failed for {}: {}", url, result.validation_report.issues)

        except Exception as e:
            self.metrics.fetch_failed += 1
            logger.error("Failed to process {}: {}", url, e)
            raise

    async def _reprocess_pending_documents(self) -> None:
        """Reprocess pending RawDocuments for this source.

        Documents may have been fetched in earlier runs but failed extraction
        (e.g. validator was too strict). When the extraction pipeline is fixed,
        we should re-attempt extraction on all pending documents for this source
        before giving up on them.

        Idempotency: scholarships already persisted are not affected; the
        extraction pipeline is stateless and a persisted scholarship with the
        same source_id will be deduplicated downstream by ScholarshipRepository.
        """
        from database.models.raw_document import RawDocument
        from services.ingestion.orchestrator import run_pipeline
        from services.ingestion.real_extractor import DeterministicLLMClient

        source_id = self.connector.config.source_id
        pending_docs = (
            self.session.query(RawDocument)
            .filter(RawDocument.source_id == source_id, RawDocument.processing_status == "pending")
            .all()
        )

        if not pending_docs:
            return

        logger.info("Reprocessing {} pending documents for source_id={}", len(pending_docs), source_id)

        llm_client = DeterministicLLMClient()
        reprocessed = 0
        for raw_doc in pending_docs:
            try:
                result = run_pipeline(str(raw_doc.document_id), self.session, llm_client)
                if result.is_valid:
                    from services.ingestion.orchestrator import persist_scholarship
                    persisted = persist_scholarship(result, str(raw_doc.document_id), self.session)
                    if persisted:
                        raw_doc.processing_status = "processed"
                        self.session.commit()
                        self.metrics.extraction_succeeded += 1
                        self.metrics.persisted += 1
                        reprocessed += 1
                        logger.info("Reprocessed pending document {}", raw_doc.source_url)
                    else:
                        self.metrics.extraction_failed += 1
                else:
                    # Validation still failing — keep as pending so future runs can retry
                    self.metrics.extraction_failed += 1
            except Exception as e:
                logger.error("Reprocess failed for {}: {}", raw_doc.source_url, e)
                self.metrics.errors.append(f"{raw_doc.source_url}: {e}")

        logger.info("Reprocessed {} of {} pending documents", reprocessed, len(pending_docs))

    def _get_seen_urls(self, urls: list[str]) -> set[str]:
        """Check which URLs have already been processed.

        Query RawDocument table for URLs matching our source.
        """
        from database.models.raw_document import RawDocument

        source_id = self.connector.config.source_id
        existing = (
            self.session.query(RawDocument.source_url)
            .filter(
                RawDocument.source_id == source_id,
                RawDocument.source_url.in_(urls)
            )
            .all()
        )
        return {url for (url,) in existing}

    def _finalize(self) -> DiscoveryMetrics:
        """Mark discovery complete and return metrics."""
        self.metrics.finished_at = datetime.now(timezone.utc)
        duration = (self.metrics.finished_at - self.metrics.started_at).total_seconds()
        logger.info(
            "Discovery complete in {:.1f}s: {} candidates, {} persisted, {} errors",
            duration,
            self.metrics.candidate_urls_found,
            self.metrics.persisted,
            len(self.metrics.errors),
        )
        return self.metrics
