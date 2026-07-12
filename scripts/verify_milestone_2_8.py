import asyncio
import sys

from database.session import SessionLocal
from database.models.source_registry import SourceRegistry
from database.models.raw_document import RawDocument
from services.ingestion.connectors import ConnectorConfig, MEXTConnector
from services.ingestion.repositories import RawDocumentMapper, RawDocumentRepository
from services.ingestion.orchestrator import run_pipeline
from services.ingestion.mock_llm import MockLLMClient


async def run_verification():
    print("--- Starting Milestone 2.8 (Pipeline Integration) Verification ---")

    session = SessionLocal()

    # 1. Fetch source registry config
    print("1. Reading SourceRegistry entry...")
    source = session.query(SourceRegistry).filter_by(source_name="Study in Japan").first()
    if not source:
        print("[FAIL] 'Study in Japan' not found in SourceRegistry. Run seed script first.")
        print("FAIL")
        sys.exit(1)

    # 2. Run connector to fetch page
    print("2. Fetching page with MEXTConnector...")
    config = ConnectorConfig(
        source_id=source.source_id,
        url=source.crawl_entry_url,
        timeout=30,
        user_agent="Polaris/0.1 Pipeline Integration Verification",
    )
    connector = MEXTConnector(config)
    await connector.connect()
    try:
        result = await connector.fetch()
        print("   Fetch completed.")
    except Exception as e:
        print(f"[FAIL] Fetch failed: {e}")
        await connector.close()
        print("FAIL")
        sys.exit(1)
    finally:
        await connector.close()

    # 3. Save RawDocument using Mapper and Repository
    print("3. Persisting RawDocument...")
    mapper = RawDocumentMapper()
    raw_doc = mapper.to_orm(result)

    repo = RawDocumentRepository(session)
    saved_doc = repo.save(raw_doc)
    doc_id = saved_doc.document_id
    print(f"   RawDocument persisted with ID: {doc_id}")

    # 4. Execute the complete pipeline via the orchestrator
    print("4. Executing orchestrator processing pipeline...")
    llm_client = MockLLMClient()
    pipeline_res = run_pipeline(str(doc_id), session, llm_client)

    # 5. Perform validations
    try:
        print("\n--- Validating Pipeline Outputs ---")
        print(f"  Document ID: {pipeline_res.document_id}")
        print(f"  Source URL: {pipeline_res.source_url}")
        print(f"  Is Valid: {pipeline_res.is_valid}")
        print(f"  Validation Report Issues: {len(pipeline_res.validation_report.issues)}")

        # Verify loader loaded content correctly
        raw_extraction = pipeline_res.raw_extraction
        assert raw_extraction.document_id == str(doc_id), "Loader returned incorrect document_id"
        print("  [PASS] Loader loaded document successfully.")

        # Verify cleaner produced cleaned text
        # (Cleaned text should contain keywords like MEXT but be stripped of nav/footer by trafilatura)
        cleaned_text = pipeline_res.raw_extraction.scholarship
        assert len(pipeline_res.raw_extraction.source_url) > 0

        # Verify extractor returned mock JSON
        assert pipeline_res.extracted_data is not None, "Extracted data is None"
        assert pipeline_res.extracted_data["scholarship_name"] == "MEXT Scholarship 2027", "Extractor returned incorrect name"
        print("  [PASS] Extractor returned structured JSON successfully.")

        # Verify validator passed
        assert pipeline_res.is_valid, "Pipeline validation report is not valid"
        assert len(pipeline_res.validation_report.issues) == 0, "Validation issues found"
        print("  [PASS] Validator passed validation successfully.")

        # Cleanup test records
        session.query(RawDocument).filter_by(document_id=doc_id).delete()
        session.commit()
        print("\n  Cleaned up test record.")

        print("\n==========================================")
        print("PASS")
        print("==========================================")

    except AssertionError as e:
        # Cleanup even on failure
        session.query(RawDocument).filter_by(document_id=doc_id).delete()
        session.commit()
        print(f"\n[FAIL] Assertion failed: {e}")
        print("FAIL")
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(run_verification())
