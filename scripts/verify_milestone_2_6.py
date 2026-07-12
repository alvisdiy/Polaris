import asyncio
import sys
import uuid

from services.ingestion.connectors import ConnectorConfig, MEXTConnector


async def run_verification():
    print("--- Starting Milestone 2.6 (MEXT Connector) Verification ---")

    # MEXT page on Study in Japan portal
    target_url = "https://www.studyinjapan.go.jp/en/planning/scholarships/"

    config = ConnectorConfig(
        source_id=uuid.uuid4(),
        url=target_url,
        timeout=30,
        user_agent="Polaris/0.1 Ingestion Verification MEXT"
    )

    connector = MEXTConnector(config)
    await connector.connect()

    try:
        result = await connector.fetch()
        print("[SUCCESS] Fetch operation completed.")
    except Exception as e:
        print(f"[FAIL] Fetch failed with error: {e}")
        await connector.close()
        print("FAIL")
        sys.exit(1)

    await connector.close()

    # Perform assertions
    try:
        print("\n--- Validating FetchResult ---")
        print(f"  Status Code: {result.status_code}")
        print(f"  Final URL: {result.final_url}")
        print(f"  Content Type: {result.content_type}")
        print(f"  HTML Length: {len(result.raw_content)} chars")
        print(f"  Crawl Duration: {result.crawl_duration_ms} ms")

        # Core assertions
        assert result.status_code == 200, f"Expected 200, got {result.status_code}"
        assert len(result.raw_content) > 1000, f"HTML length {len(result.raw_content)} too short"

        # Check content-type header
        ct_header = result.headers.get("content-type", "").lower()
        assert "text/html" in ct_header, f"Expected text/html in content-type header, got: {ct_header}"

        # Check crawl duration
        assert result.crawl_duration_ms is not None and result.crawl_duration_ms > 0, "Crawl duration must be > 0"

        # Extract output test
        extracted_html = connector.extract(result)
        assert extracted_html == result.raw_content, "Extractor must return raw HTML content"

        print("\n==========================================")
        print("PASS")
        print("==========================================")
    except AssertionError as e:
        print(f"\n[FAIL] Assertion failed: {e}")
        print("FAIL")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_verification())
