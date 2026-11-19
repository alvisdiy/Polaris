"""Run the MEXT (Study in Japan) pipeline end to end.

Operator script, not a service:

    discover candidate URLs -> fetch -> RawDocument -> extract -> validate ->
    persist as ``pending_review``

It never approves anything. Review is the publication boundary; a crawler that
can publish is a review bypass.

This script is lower-level than ``run_country_exploration.py`` and does not
carry that runner's scratch-database guard. Point ``DATABASE_URL`` at a
disposable database explicitly before running it.
"""

import asyncio
import sys
from uuid import UUID

from loguru import logger

from database.models.source_registry import SourceRegistry
from database.session import get_session_local
from services.discovery import discover_scholarships_for_country_async
from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.orchestrator import persist_scholarship, run_pipeline
from services.ingestion.real_extractor import DeterministicLLMClient
from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
from services.ingestion.repositories.raw_document_repository import RawDocumentRepository


def get_mext_source(session) -> SourceRegistry:
    """Fetch the MEXT source from the Source Registry."""
    source = (
        session.query(SourceRegistry)
        .filter_by(connector_name="mext_connector")
        .first()
    )
    if not source:
        raise RuntimeError(
            "MEXT source not found in Source Registry. "
            "Run: python scripts/seed_source_registry.py"
        )
    return source


def get_mext_source_by_id(source_id: UUID, session) -> SourceRegistry:
    """Fetch a MEXT source by id (kept for tests/tooling)."""
    source = session.query(SourceRegistry).filter_by(source_id=source_id).first()
    if not source:
        raise RuntimeError(f"MEXT source {source_id} not found")
    return source


def store_raw_document(fetch_result, session) -> str:
    """Map a FetchResult to RawDocument and persist it. Returns document_id."""
    mapper = RawDocumentMapper()
    raw_doc = mapper.to_orm(fetch_result)

    repo = RawDocumentRepository(session)

    existing = repo.get_by_source_and_checksum(raw_doc.source_id, raw_doc.checksum)
    if existing:
        logger.info("RawDocument already exists (checksum match): {}", existing.document_id)
        return str(existing.document_id)

    saved = repo.save(raw_doc)
    logger.info("Stored RawDocument: {}", saved.document_id)
    return str(saved.document_id)


def run_extraction(document_id: str, session):
    """Run the extraction pipeline and persist the scholarship."""
    llm_client = DeterministicLLMClient()
    logger.info("Running pipeline for document_id={}", document_id)

    result = run_pipeline(document_id, session, llm_client)

    if not result.is_valid:
        logger.error("Validation failed: {}", result.validation_report.issues)
        return None

    scholarship = persist_scholarship(result, document_id, session)

    if scholarship:
        # The record lands in pending_review and stops there. Approving it here
        # would make this script a publication bypass: crawler output would
        # reach the public API with no reviewer, no version row and no audit
        # action.
        session.commit()
        logger.info(
            "Scholarship persisted for review: id={} name='{}' state={}",
            scholarship.scholarship_id,
            scholarship.scholarship_name,
            scholarship.extraction_status,
        )
    else:
        logger.warning("persist_scholarship returned None")

    return scholarship


async def run_mext_pipeline() -> int:
    """Run the full MEXT pipeline with scholarship-first discovery."""
    logger.info("=== MEXT Pipeline Start ===")

    session = get_session_local()()
    connector = None

    try:
        source = get_mext_source(session)
        logger.info("Source: {} ({})", source.source_name, source.status)

        # The async form is required here: this function already owns an event
        # loop, and the blocking wrapper would call asyncio.run() inside it.
        candidates = await discover_scholarships_for_country_async("JP", session)
        logger.info("Found {} scholarship candidates", len(candidates))

        for item in candidates:
            scholarship_url = item.get("url") if isinstance(item, dict) else str(item)
            if not scholarship_url:
                continue
            logger.info("Processing scholarship URL: {}", scholarship_url)

            try:
                config = ConnectorConfig(
                    source_id=source.source_id,
                    url=scholarship_url,
                    timeout=30,
                    max_retries=2,
                )

                connector = _instantiate_connector(source.connector_name, config)
                await connector.connect()
                try:
                    result = await connector.fetch()
                finally:
                    await connector.close()
                    connector = None

                document_id = store_raw_document(result, session)
                scholarship = run_extraction(document_id, session)

                if scholarship:
                    logger.info("✓ Successfully processed: {}", scholarship.scholarship_name)
                else:
                    logger.warning("Failed to process: {}", scholarship_url)

            except Exception as exc:  # noqa: BLE001 — one URL must not stop the batch
                logger.error("Failed processing {}: {}", scholarship_url, exc)
                continue

        logger.info("=== MEXT Pipeline Complete ===")
        return 0

    except Exception as exc:  # noqa: BLE001 — report and exit non-zero
        logger.exception("Pipeline failed: {}", exc)
        return 1
    finally:
        if connector is not None:
            await connector.close()
        session.close()


def _instantiate_connector(connector_name: str, config: ConnectorConfig):
    """Dynamically instantiate a connector by name."""
    connector_map = {
        "mext_connector": (
            "services.ingestion.connectors.government.mext_connector",
            "MEXTConnector",
        ),
        "generic_http": (
            "services.ingestion.connectors.generic_connector",
            "GenericHTTPConnector",
        ),
        "generic_playwright": (
            "services.ingestion.connectors.generic_playwright",
            "GenericPlaywrightConnector",
        ),
    }

    if connector_name not in connector_map:
        raise ValueError(f"Unknown connector: {connector_name}")

    module_path, class_name = connector_map[connector_name]
    try:
        module = __import__(module_path, fromlist=[class_name])
        connector_class = getattr(module, class_name)
        return connector_class(config)
    except Exception as exc:  # noqa: BLE001 — re-raised with context
        raise ValueError(f"Failed to instantiate connector {connector_name}: {exc}")


def main() -> int:
    return asyncio.run(run_mext_pipeline())


if __name__ == "__main__":
    sys.exit(main())
