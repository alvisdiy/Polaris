import asyncio
import hashlib
import uuid

from database.session import SessionLocal
from database.models.source_registry import SourceRegistry
from services.ingestion.connectors import ConnectorConfig, MEXTConnector
from services.ingestion.repositories import RawDocumentMapper, RawDocumentRepository


async def verify_milestone_2_7():
    print("--- Starting Milestone 2.7 (RawDocument Persistence) Verification ---")

    session = SessionLocal()

    # 1. Read SourceRegistry entry
    print("1. Querying 'Study in Japan' source registry...")
    source = session.query(SourceRegistry).filter_by(source_name="Study in Japan").first()
    if not source:
        print("[FAIL] 'Study in Japan' not found in SourceRegistry. Run seed script first.")
        return

    print(f"  source_id: {source.source_id}")
    print(f"  entry_url: {source.crawl_entry_url}")

    # 2. Run the connector
    config = ConnectorConfig(
        source_id=source.source_id,
        url=source.crawl_entry_url,
        timeout=30,
        user_agent="Polaris/0.1 RawDocument Persistence Verification",
    )

    connector = MEXTConnector(config)
    await connector.connect()

    try:
        result = await connector.fetch()
        print("[SUCCESS] Fetch completed.")
    except Exception as e:
        print(f"[FAIL] Fetch failed: {e}")
        await connector.close()
        return
    finally:
        await connector.close()

    # 3. Map to ORM
    print("\n2. Mapping FetchResult -> RawDocument ORM...")
    mapper = RawDocumentMapper()
    raw_doc = mapper.to_orm(result)
    print(f"  checksum: {raw_doc.checksum}")
    print(f"  source_url: {raw_doc.source_url}")

    # 4. Save via repository
    print("\n3. Persisting RawDocument via repository...")
    repo = RawDocumentRepository(session)
    saved_doc = repo.save(raw_doc)
    print(f"  document_id: {saved_doc.document_id}")

    # 5. Read back from DB
    print("\n4. Reading back from PostgreSQL...")
    read_back = repo.get_by_id(saved_doc.document_id)
    assert read_back is not None, "Document not found after save"
    print(f"  document_id: {read_back.document_id}")

    # 6. Verify fields
    print("\n5. Verifying fields...")
    expected_checksum = hashlib.sha256(result.raw_content.encode("utf-8")).hexdigest()

    checks = {
        "checksum": (read_back.checksum, expected_checksum),
        "status_code": (read_back.status_code, result.status_code),
        "etag": (read_back.etag, result.etag),
        "last_modified": (read_back.last_modified, result.last_modified),
        "fetched_at": (read_back.fetched_at, result.crawl_time),
        "processing_status": (read_back.processing_status, "pending"),
    }

    all_passed = True
    for field_name, (actual, expected) in checks.items():
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        print(f"  {field_name:20s} actual={actual} expected={expected} [{status}]")
        if not ok:
            all_passed = False

    # Cleanup test record
    session.delete(read_back)
    session.commit()
    print("\n  Cleaned up test record.")

    session.close()

    print("\n==========================================")
    if all_passed:
        print("PASS")
    else:
        print("FAIL")
    print("==========================================")


if __name__ == "__main__":
    asyncio.run(verify_milestone_2_7())
