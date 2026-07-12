"""End-to-end MEXT pipeline: fetch → RawDocument → extract → Scholarship.

Usage:
    python scripts/run_mext_pipeline.py

Requires:
    - DATABASE_URL set in environment or .env
    - Seed data loaded (run scripts/seed_source_registry.py first)
"""

from __future__ import annotations

import asyncio
import sys

from loguru import logger

from database.models.source_registry import SourceRegistry
from database.session import get_session_local
from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.government.mext_connector import MEXTConnector
from services.ingestion.mock_llm import MockLLMClient
from services.ingestion.orchestrator import persist_scholarship, run_pipeline
from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
from services.ingestion.repositories.raw_document_repository import RawDocumentRepository

# MEXT entry URL from Source Registry seed data
MEXT_CRAWL_URL = "https://www.studyinjapan.go.jp/en/"


def get_mext_source(session) -> SourceRegistry:
    """Fetch the MEXT source from Source Registry."""
    source = session.query(SourceRegistry).filter_by(connector_name="mext_connector").first()
    if not source:
        raise RuntimeError(
            "MEXT source not found in Source Registry. "
            "Run: python scripts/seed_source_registry.py"
        )
    return source


async def fetch_mext_page(source: SourceRegistry) -> tuple:
    """Fetch the MEXT page and return (fetch_result, connector)."""
    config = ConnectorConfig(
        source_id=source.source_id,
        url=MEXT_CRAWL_URL,
        timeout=30,
        user_agent="PolarisBot/0.1 (scholarship research)",
    )

    connector = MEXTConnector(config)
    try:
        await connector.connect()
        logger.info("Fetching MEXT page: {}", MEXT_CRAWL_URL)
        result = await connector.fetch()
        logger.info("Fetched {} bytes, status={}", result.response_size, result.status_code)
        return result, connector
    except Exception:
        await connector.close()
        raise


def store_raw_document(fetch_result, session) -> str:
    """Map FetchResult to RawDocument and persist. Returns document_id."""
    mapper = RawDocumentMapper()
    raw_doc = mapper.to_orm(fetch_result)

    repo = RawDocumentRepository(session)

    # Check for duplicate
    existing = repo.get_by_source_and_checksum(raw_doc.source_id, raw_doc.checksum)
    if existing:
        logger.info("RawDocument already exists (checksum match): {}", existing.document_id)
        return str(existing.document_id)

    saved = repo.save(raw_doc)
    logger.info("Stored RawDocument: {}", saved.document_id)
    return str(saved.document_id)


def run_extraction(document_id: str, session):
    """Run the extraction pipeline and persist the scholarship."""
    llm_client = MockLLMClient()
    logger.info("Running pipeline for document_id={}", document_id)

    result = run_pipeline(document_id, session, llm_client)

    if not result.is_valid:
        logger.error("Validation failed: {}", result.validation_report.issues)
        return None

    logger.info("Extraction valid. Persisting scholarship...")
    scholarship = persist_scholarship(result, document_id, session)

    if scholarship:
        logger.info(
            "Scholarship persisted: id={} name='{}' status={}",
            scholarship.scholarship_id,
            scholarship.scholarship_name,
            scholarship.extraction_status,
        )
    else:
        logger.warning("persist_scholarship returned None")

    return scholarship


def main():
    """Run the full MEXT pipeline."""
    logger.info("=== MEXT Pipeline Start ===")

    SessionLocal = get_session_local()
    session = SessionLocal()
    connector = None

    try:
        # 1. Get source from registry
        source = get_mext_source(session)
        logger.info("Source: {} ({})", source.source_name, source.status)

        # 2. Fetch page
        fetch_result, connector = asyncio.run(fetch_mext_page(source))

        # 3. Store RawDocument
        document_id = store_raw_document(fetch_result, session)

        # 4. Run extraction pipeline
        scholarship = run_extraction(document_id, session)

        if scholarship:
            logger.info("=== Pipeline Success ===")
            logger.info("Scholarship ID: {}", scholarship.scholarship_id)
            logger.info("Name: {}", scholarship.scholarship_name)
            logger.info("Status: {}", scholarship.extraction_status)
            return 0
        else:
            logger.error("=== Pipeline Failed: No scholarship persisted ===")
            return 1

    except Exception as e:
        logger.exception("Pipeline failed: {}", e)
        return 1
    finally:
        if connector:
            asyncio.run(connector.close())
        session.close()


if __name__ == "__main__":
    sys.exit(main())
