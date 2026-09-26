import asyncio
import sys
import os
from loguru import logger

from database.models.source_registry import SourceRegistry
from database.session import get_session_local
from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.government.mext_connector import MEXTConnector
from services.ingestion.real_extractor import DeterministicLLMClient
from services.ingestion.orchestrator import persist_scholarship, run_pipeline
from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
from services.ingestion.repositories.raw_document_repository import RawDocumentRepository
from services.ingestion.discovery import discover_scholarships_for_country


def get_mext_source(session) -> SourceRegistry:
    """Fetch the MEXT source from Source Registry."""
    source = session.query(SourceRegistry).filter_by(connector_name="mext_connector").first()
    if not source:
        raise RuntimeError(
            "MEXT source not found in Source Registry. "
            "Run: python scripts/seed_source_registry.py"
        )
    return source


def get_mext_source_by_id(source_id: UUID, session) -> SourceRegistry:
    """Fetch MEXT source by ID (for testing)."""
    source = session.query(SourceRegistry).filter_by(source_id=source_id).first()
    if not source:
        raise RuntimeError(f"MEXT source {source_id} not found")
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
    llm_client = DeterministicLLMClient()
    logger.info("Running pipeline for document_id={}", document_id)

    result = run_pipeline(document_id, session, llm_client)

    if not result.is_valid:
        logger.error("Validation failed: {}", result.validation_report.issues)
        return None

    scholarship = persist_scholarship(result, document_id, session)

    if scholarship:
        # Auto-approve for MVP (no human review UI yet)
        scholarship.extraction_status = "approved"
        session.commit()
        logger.info(
            "Scholarship persisted & approved: id={} name='{}'",
            scholarship.scholarship_id,
            scholarship.scholarship_name,
        )
    else:
        logger.warning("persist_scholarship returned None")

    return scholarship


def run_mext_pipeline():
    """Run the full MEXT pipeline with enhanced discovery."""
    logger.info("=== MEXT Pipeline Start ===")

    SessionLocal = get_session_local()
    session = SessionLocal()
    connector = None

    try:
        # 1. Get source from registry
        source = get_mext_source(session)
        logger.info("Source: {} ({})", source.source_name, source.status)

        # 1.1 NEW: Discover scholarships from all registered sources for Japan
        logger.info("Discovering scholarships for Japan...")
        scholarships = discover_scholarships_for_country("JP", session)
        logger.info("Found {} scholarship candidates", len(scholarships))

        # 2. Process each candidate URL
        for scholarship_url in scholarships:
            logger.info("Processing scholarship URL: {}", scholarship_url)

            try:
                # Create connector config for this specific URL
                config = ConnectorConfig(
                    source_id=source.source_id,
                    url=scholarship_url,
                    timeout=30,
                    max_retries=2,
                )

                connector = _instantiate_connector(source.connector_name, config)
                await connector.connect()

                result = await connector.fetch()
                document_id = store_raw_document(result, session)

                # Run extraction pipeline
                scholarship = run_extraction(document_id, session)

                if scholarship:
                    logger.info("✓ Successfully processed: {}", scholarship.scholarship_name)
                else:
                    logger.warning("Failed to process: {}", scholarship_url)

            except Exception as e:
                logger.error("Failed processing {}: {}", scholarship_url, e)
                continue

        logger.info("=== MEXT Pipeline Complete ===")
        return 0

    except Exception as e:
        logger.exception("Pipeline failed: {}", e)
        return 1
    finally:
        if connector:
            asyncio.run(connector.close())
        session.close()


def _instantiate_connector(connector_name: str, config: ConnectorConfig):
    """Dynamically instantiate a connector by name."""
    connector_map = {
        "mext_connector": ("services.ingestion.connectors.government.mext_connector", "MEXTConnector"),
        "generic_http": ("services.ingestion.connectors.generic_connector", "GenericHTTPConnector"),
        "generic_playwright": ("services.ingestion.connectors.generic_playwright", "GenericPlaywrightConnector"),
    }

    if connector_name not in connector_map:
        raise ValueError(f"Unknown connector: {connector_name}")

    module_path, class_name = connector_map[connector_name]
    try:
        module = __import__(module_path, fromlist=[class_name])
        connector_class = getattr(module, class_name)
        return connector_class(config)
    except Exception as e:
        raise ValueError(f"Failed to instantiate connector {connector_name}: {e}")


if __name__ == "__main__":
    sys.exit(main())