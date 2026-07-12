import asyncio
import uuid
from pydantic import ValidationError
from services.ingestion.connectors import (
    BaseConnector,
    ConnectorConfig,
    FetchResult,
    ConnectorHTTPException,
    ConnectorRateLimitException,
    ConnectorTimeoutException,
)

class MockConnector(BaseConnector):
    async def connect(self) -> None:
        pass

    async def fetch(self) -> FetchResult:
        url = str(self.config.url)
        if url.endswith("timeout"):
            raise ConnectorTimeoutException("Connection timed out", source_id=self.config.source_id)
        if url.endswith("404"):
            raise ConnectorHTTPException("Not Found", status_code=404, source_id=self.config.source_id)
        if url.endswith("429"):
            raise ConnectorRateLimitException("Too Many Requests", retry_after=60, source_id=self.config.source_id)

        return FetchResult(
            source_id=self.config.source_id,
            raw_content="<html><body>Mock Content</body></html>",
            content_type="html",
            status_code=200,
            processing_time_ms=120.5,
            retry_count=0,
            headers={"Content-Type": "text/html"},
            final_url=str(self.config.url),
            response_size=42,
            encoding="utf-8",
        )

    async def close(self) -> None:
        pass


async def run_verification():
    print("--- Starting Milestone 2.1 Verification ---")
    source_id = uuid.uuid4()

    # 1. Verify Configuration Validation
    print("1. Testing ConnectorConfig validation...")
    try:
        config = ConnectorConfig(
            source_id=source_id,
            url="https://official-source.gov/scholarships",
            timeout=45,
            max_retries=2,
            backoff_factor=1.5,
            headers={"Authorization": "Bearer token"},
            user_agent="Polaris/0.1",
        )
        print(f"[SUCCESS] ConnectorConfig initialized correctly for URL: {config.url}")
    except Exception as e:
        print(f"[FAIL] ConnectorConfig initialization failed: {e}")
        raise e

    # Test invalid configuration parameters
    try:
        ConnectorConfig(
            source_id=source_id,
            url="not-a-valid-url",
        )
        print("[FAIL] ConnectorConfig accepted an invalid URL!")
        raise AssertionError("Accepted invalid URL")
    except ValidationError:
        print("[SUCCESS] ConnectorConfig correctly rejected invalid URL")

    # 2. Verify Successful Fetch
    print("\n2. Testing successful fetch...")
    connector = MockConnector(config)
    await connector.connect()
    try:
        result = await connector.fetch()
        assert result.source_id == source_id
        assert result.content_type == "html"
        assert result.status_code == 200
        assert "Mock Content" in result.raw_content
        assert result.final_url == str(config.url)
        assert result.response_size == 42
        assert result.encoding == "utf-8"
        print(f"[SUCCESS] FetchResult verified. Processing time: {result.processing_time_ms} ms")
    except Exception as e:
        print(f"[FAIL] Fetch failed: {e}")
        raise e

    # 3. Verify Content Type Validation
    print("\n3. Testing FetchResult content_type constraint...")
    try:
        FetchResult(
            source_id=source_id,
            raw_content="Mock Content",
            content_type="docx",  # Invalid type (only html, pdf, json, markdown allowed)
            processing_time_ms=10.0,
            retry_count=0
        )
        print("[FAIL] FetchResult accepted an invalid content_type!")
        raise AssertionError("Accepted invalid content_type")
    except ValidationError:
        print("[SUCCESS] FetchResult correctly rejected invalid content_type")

    # 4. Verify Exception Scenarios
    print("\n4. Testing exception propagation...")
    timeout_config = ConnectorConfig(
        source_id=source_id,
        url="https://official-source.gov/timeout"
    )
    timeout_connector = MockConnector(timeout_config)
    try:
        await timeout_connector.fetch()
        print("[FAIL] Timeout connector did not throw Exception!")
        raise AssertionError("No exception on timeout")
    except ConnectorTimeoutException as e:
        print(f"[SUCCESS] Correctly caught: {type(e).__name__} - {e}")

    http_config = ConnectorConfig(
        source_id=source_id,
        url="https://official-source.gov/404"
    )
    http_connector = MockConnector(http_config)
    try:
        await http_connector.fetch()
        print("[FAIL] HTTP 404 connector did not throw Exception!")
        raise AssertionError("No exception on HTTP 404")
    except ConnectorHTTPException as e:
        assert e.status_code == 404
        print(f"[SUCCESS] Correctly caught: {type(e).__name__} (Status: {e.status_code})")

    await connector.close()
    print("\n[SUCCESS] Milestone 2.1 Verification passed!")


if __name__ == "__main__":
    asyncio.run(run_verification())
