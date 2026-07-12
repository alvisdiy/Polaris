import asyncio
import sys
import hashlib
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError

from database.session import SessionLocal
from database.models.source_registry import SourceRegistry
from database.models.raw_document import RawDocument
from services.ingestion.connectors import ConnectorConfig, StudyInJapanConnector


async def verify_milestone_2_4():
    print("--- Starting Milestone 2.4 (RawDocument) Verification ---")
    session = SessionLocal()

    # 1. Fetch source registry config
    source = session.query(SourceRegistry).filter_by(source_name="Study in Japan").first()
    if not source:
        print("[FAIL] 'Study in Japan' not found in SourceRegistry database. Seed database first.")
        sys.exit(1)

    print(f"Source Registry ID: {source.source_id}")

    # 2. Instantiate and run StudyInJapanConnector
    config = ConnectorConfig(
        source_id=source.source_id,
        url=source.crawl_entry_url,
        timeout=30,
        max_retries=3,
        backoff_factor=2.0,
        user_agent="Polaris/0.1 Ingestion Pipeline Verification"
    )

    connector = StudyInJapanConnector(config)
    await connector.connect()
    try:
        result = await connector.fetch()
        print("[SUCCESS] Fetch operation completed.")
    except Exception as e:
        print(f"[FAIL] Fetch failed: {e}")
        await connector.close()
        sys.exit(1)
    finally:
        await connector.close()

    # 3. Compute Checksum
    content_bytes = result.raw_content.encode("utf-8")
    checksum = hashlib.sha256(content_bytes).hexdigest()
    print(f"Computed SHA256 Checksum: {checksum}")

    # Clean existing test raw documents for this checksum to ensure fresh start
    session.query(RawDocument).filter_by(source_id=source.source_id, checksum=checksum).delete()
    session.commit()

    # 4. Insert into RawDocument
    print("Inserting RawDocument into database...")
    doc = RawDocument(
        source_id=source.source_id,
        source_url=str(result.final_url or config.url),
        content_type=result.content_type,
        raw_content=result.raw_content,
        checksum=checksum,
        status_code=result.status_code,
        fetched_at=result.crawl_time,
        etag=result.etag,
        last_modified=result.last_modified,
        crawl_duration_ms=result.crawl_duration_ms,
    )
    session.add(doc)
    session.commit()
    print(f"[SUCCESS] Inserted RawDocument with ID: {doc.document_id}")

    # 5. Query and Validate Fields
    db_doc = session.query(RawDocument).filter_by(document_id=doc.document_id).first()
    if not db_doc:
        print("[FAIL] RawDocument not found in database after insertion.")
        sys.exit(1)

    print("\n--- Validating Database Fields ---")
    print(f"  document_id: {db_doc.document_id}")
    print(f"  source_id: {db_doc.source_id}")
    print(f"  source_url: {db_doc.source_url}")
    print(f"  content_type: {db_doc.content_type}")
    print(f"  checksum: {db_doc.checksum}")
    print(f"  status_code: {db_doc.status_code}")
    print(f"  fetched_at: {db_doc.fetched_at}")
    print(f"  etag: {db_doc.etag}")
    print(f"  last_modified: {db_doc.last_modified}")
    print(f"  crawl_duration_ms: {db_doc.crawl_duration_ms}")
    print(f"  processing_status: {db_doc.processing_status}")
    print(f"  created_at: {db_doc.created_at}")
    print(f"  updated_at: {db_doc.updated_at}")

    assert db_doc.processing_status == "pending", f"Expected 'pending', got {db_doc.processing_status}"
    assert db_doc.source_id == source.source_id
    assert db_doc.checksum == checksum
    assert db_doc.crawl_duration_ms is not None and db_doc.crawl_duration_ms > 0

    # 6. Verify Idempotency constraint (UniqueConstraint on source_id, checksum)
    print("\nVerifying Idempotency constraint (must raise IntegrityError on duplicate insertion)...")
    duplicate_doc = RawDocument(
        source_id=source.source_id,
        source_url=str(result.final_url or config.url),
        content_type=result.content_type,
        raw_content=result.raw_content,
        checksum=checksum,
        status_code=result.status_code,
        fetched_at=result.crawl_time,
        etag=result.etag,
        last_modified=result.last_modified,
        crawl_duration_ms=result.crawl_duration_ms,
    )
    session.add(duplicate_doc)
    try:
        session.commit()
        print("[FAIL] Inserted duplicate document without raising IntegrityError.")
        sys.exit(1)
    except IntegrityError:
        session.rollback()
        print("[SUCCESS] IntegrityError raised successfully on duplicate insertion.")

    # Cleanup after test
    session.query(RawDocument).filter_by(document_id=doc.document_id).delete()
    session.commit()
    print("Cleaned up test document.")

    session.close()
    print("\n==========================================")
    print("[SUCCESS] Milestone 2.4 Verification Passed!")
    print("==========================================")


if __name__ == "__main__":
    asyncio.run(verify_milestone_2_4())
