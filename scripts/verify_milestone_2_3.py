import asyncio
import sys
from database.session import SessionLocal
from database.models.source_registry import SourceRegistry
from services.ingestion.connectors import ConnectorConfig, StudyInJapanConnector


async def verify_milestone_2_3():
    print("--- Starting Milestone 2.3 Verification ---")
    session = SessionLocal()

    # 1. Read configuration from SourceRegistry in DB
    print("1. Querying 'Study in Japan' source registry config from DB...")
    source = session.query(SourceRegistry).filter_by(source_name="Study in Japan").first()
    if not source:
        print("[FAIL] 'Study in Japan' not found in SourceRegistry database. Seed database first.")
        sys.exit(1)

    print(f"  ID: {source.source_id}")
    print(f"  Name: {source.source_name}")
    print(f"  Entry URL: {source.crawl_entry_url}")
    print(f"  Crawl Method: {source.crawl_method}")

    # Map database row to ConnectorConfig
    config = ConnectorConfig(
        source_id=source.source_id,
        url=source.crawl_entry_url,  # using entry url for crawling
        timeout=30,
        max_retries=3,
        backoff_factor=2.0,
        user_agent="Polaris/0.1 Ingestion Pipeline Verification"
    )

    # 2. Instantiate and run StudyInJapanConnector
    print("\n2. Initializing StudyInJapanConnector...")
    connector = StudyInJapanConnector(config)

    print("3. Executing connect()...")
    await connector.connect()

    print("4. Executing fetch()...")
    try:
        result = await connector.fetch()
        print("[SUCCESS] Fetch operation completed successfully.")
    except Exception as e:
        print(f"[FAIL] Fetch failed: {e}")
        await connector.close()
        sys.exit(1)

    print("5. Executing close()...")
    await connector.close()

    # 3. Perform Validations
    print("\n--- Performing Validations ---")

    validation_errors = []

    # Check status_code
    print(f"  Status Code: {result.status_code}")
    if result.status_code != 200:
        validation_errors.append(f"Expected HTTP 200, got {result.status_code}")

    # Check content_type
    print(f"  Content Type: {result.content_type}")
    if result.content_type != "html":
        validation_errors.append(f"Expected content_type 'html', got '{result.content_type}'")

    # Check raw_content length
    raw_len = len(result.raw_content)
    print(f"  Raw Content Length: {raw_len} chars")
    if raw_len == 0:
        validation_errors.append("raw_content is empty")

    # Check response_size
    print(f"  Response Size: {result.response_size} bytes")
    if not result.response_size or result.response_size <= 0:
        validation_errors.append(f"Expected response_size > 0, got {result.response_size}")

    # Check final_url
    print(f"  Final URL: {result.final_url}")
    if not result.final_url:
        validation_errors.append("final_url is not populated")

    # Check performance metric
    print(f"  Crawl time: {result.crawl_time}")
    print(f"  Processing time: {result.processing_time_ms:.2f} ms")

    session.close()

    # Report results
    print("\n==========================================")
    if validation_errors:
        print("[FAIL] Validation failed with errors:")
        for err in validation_errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("[SUCCESS] Milestone 2.3 Verification Passed!")
        print("==========================================")


if __name__ == "__main__":
    asyncio.run(verify_milestone_2_3())
