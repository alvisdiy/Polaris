"""Tests for connector pattern (M2.1)."""

import uuid

import pytest
from pydantic import ValidationError

from services.ingestion.connectors import (
    BaseConnector,
    ConnectorConfig,
    ConnectorHTTPException,
    ConnectorRateLimitException,
    ConnectorTimeoutException,
    FetchResult,
)

pytestmark = pytest.mark.unit


class MockConnector(BaseConnector):
    """Mock connector for testing."""

    async def connect(self) -> None:
        pass

    async def fetch(self) -> FetchResult:
        url = str(self.config.url)
        if url.endswith("timeout"):
            raise ConnectorTimeoutException("Timeout", source_id=self.config.source_id)
        if url.endswith("404"):
            raise ConnectorHTTPException("Not Found", status_code=404, source_id=self.config.source_id)
        if url.endswith("429"):
            raise ConnectorRateLimitException("Rate limited", retry_after=60, source_id=self.config.source_id)

        return FetchResult(
            source_id=self.config.source_id,
            raw_content="<html><body>Mock</body></html>",
            content_type="html",
            status_code=200,
            processing_time_ms=100.0,
            retry_count=0,
            headers={"Content-Type": "text/html"},
            final_url=str(self.config.url),
            response_size=42,
            encoding="utf-8",
        )

    async def close(self) -> None:
        pass


class TestConnectorConfig:
    """ConnectorConfig validation tests."""

    def test_valid_config(self):
        config = ConnectorConfig(
            source_id=uuid.uuid4(),
            url="https://example.com/scholarships",
            timeout=30,
            max_retries=3,
        )
        assert str(config.url) == "https://example.com/scholarships"

    def test_invalid_url_rejected(self):
        with pytest.raises(ValidationError):
            ConnectorConfig(source_id=uuid.uuid4(), url="not-a-url")


class TestFetchResult:
    """FetchResult validation tests."""

    def test_valid_result(self):
        result = FetchResult(
            source_id=uuid.uuid4(),
            raw_content="content",
            content_type="html",
            processing_time_ms=100.0,
            retry_count=0,
        )
        assert result.content_type == "html"

    def test_invalid_content_type_rejected(self):
        with pytest.raises(ValidationError):
            FetchResult(
                source_id=uuid.uuid4(),
                raw_content="content",
                content_type="docx",
                processing_time_ms=100.0,
                retry_count=0,
            )


class TestMockConnector:
    """MockConnector fetch and exception tests."""

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        config = ConnectorConfig(source_id=uuid.uuid4(), url="https://example.com")
        connector = MockConnector(config)
        await connector.connect()
        result = await connector.fetch()
        assert result.status_code == 200
        assert "Mock" in result.raw_content
        await connector.close()

    @pytest.mark.asyncio
    async def test_timeout_exception(self):
        config = ConnectorConfig(source_id=uuid.uuid4(), url="https://example.com/timeout")
        connector = MockConnector(config)
        await connector.connect()
        with pytest.raises(ConnectorTimeoutException):
            await connector.fetch()
        await connector.close()

    @pytest.mark.asyncio
    async def test_http_404_exception(self):
        config = ConnectorConfig(source_id=uuid.uuid4(), url="https://example.com/404")
        connector = MockConnector(config)
        await connector.connect()
        with pytest.raises(ConnectorHTTPException) as exc_info:
            await connector.fetch()
        assert exc_info.value.status_code == 404
        await connector.close()

    @pytest.mark.asyncio
    async def test_rate_limit_exception(self):
        config = ConnectorConfig(source_id=uuid.uuid4(), url="https://example.com/429")
        connector = MockConnector(config)
        await connector.connect()
        with pytest.raises(ConnectorRateLimitException):
            await connector.fetch()
        await connector.close()
