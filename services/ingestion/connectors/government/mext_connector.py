"""HTTP connector for Study in Japan (MEXT) official scholarship page.

Uses httpx for fetching — no browser automation.
"""

import time
from datetime import datetime, timezone

import httpx
from loguru import logger

from services.ingestion.connectors.base_connector import (
    BaseConnector,
    ConnectorConfig,
    ConnectorHTTPException,
    ConnectorRateLimitException,
    ConnectorSecurityException,
    ConnectorTimeoutException,
    FetchResult,
)


class MEXTConnector(BaseConnector):
    """httpx-based connector for MEXT scholarship pages on studyinjapan.go.jp."""

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Create an httpx async client with configured timeout and headers."""
        logger.info("MEXTConnector connecting source_id={}", self.config.source_id)
        try:
            headers = dict(self.config.headers)
            if self.config.user_agent:
                headers["User-Agent"] = self.config.user_agent

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10),
                follow_redirects=True,
                headers=headers,
                verify=True,
            )
        except Exception as e:
            await self.close()
            raise ConnectorSecurityException(
                f"Failed to create HTTP client: {e}",
                source_id=self.config.source_id,
            )

    async def fetch(self) -> FetchResult:
        """Fetch the configured URL and return raw HTML content."""
        if not self._client:
            raise ConnectorSecurityException(
                "Not connected. Call connect() first.",
                source_id=self.config.source_id,
            )

        url = str(self.config.url)
        logger.info("MEXTConnector fetching url={} source_id={}", url, self.config.source_id)
        start = time.perf_counter()

        try:
            response = await self._client.get(url)
        except httpx.TimeoutException as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("MEXTConnector timeout url={} elapsed={:.0f}ms", url, elapsed)
            raise ConnectorTimeoutException(
                f"Timeout fetching {url}: {e}",
                source_id=self.config.source_id,
            )
        except httpx.SSLError as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("MEXTConnector SSL error url={} elapsed={:.0f}ms", url, elapsed)
            raise ConnectorSecurityException(
                f"SSL error fetching {url}: {e}",
                source_id=self.config.source_id,
            )
        except httpx.RequestError as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning("MEXTConnector request error url={} elapsed={:.0f}ms", url, elapsed)
            raise ConnectorHTTPException(
                f"Request error fetching {url}: {e}",
                status_code=0,
                source_id=self.config.source_id,
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        status = response.status_code

        if status == 429:
            retry_after = response.headers.get("retry-after")
            retry_val = int(retry_after) if retry_after and retry_after.isdigit() else None
            logger.warning("MEXTConnector rate limited url={} retry_after={}", url, retry_val)
            raise ConnectorRateLimitException(
                f"Rate limited fetching {url}",
                retry_after=retry_val,
                source_id=self.config.source_id,
            )

        if status < 200 or status >= 300:
            logger.warning("MEXTConnector HTTP {} url={}", status, url)
            raise ConnectorHTTPException(
                f"HTTP {status} fetching {url}",
                status_code=status,
                source_id=self.config.source_id,
            )

        # Content type validation
        content_type_header = response.headers.get("content-type", "")
        if "text/html" not in content_type_header and "text/" not in content_type_header:
            logger.warning(
                "MEXTConnector unexpected content_type={} url={}",
                content_type_header,
                url,
            )
            raise ConnectorHTTPException(
                f"Unexpected content type: {content_type_header}",
                status_code=status,
                source_id=self.config.source_id,
            )

        raw_content = response.text
        headers = dict(response.headers)
        encoding = "utf-8"
        if "charset=" in content_type_header:
            encoding = content_type_header.split("charset=")[-1].strip()

        logger.info(
            "MEXTConnector fetched url={} status={} elapsed={:.0f}ms size={}",
            url,
            status,
            elapsed_ms,
            len(raw_content),
        )

        return FetchResult(
            source_id=self.config.source_id,
            raw_content=raw_content,
            content_type="html",
            final_url=str(response.url),
            response_size=len(raw_content.encode("utf-8")),
            encoding=encoding,
            status_code=status,
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
            crawl_duration_ms=int(elapsed_ms),
            crawl_time=datetime.now(timezone.utc),
            processing_time_ms=elapsed_ms,
            retry_count=0,
            headers=headers,
        )

    def extract(self, fetch_result: FetchResult) -> str:
        """Return raw HTML content from FetchResult.

        This connector does not parse or clean — extraction is the
        pipeline cleaner's responsibility.
        """
        return fetch_result.raw_content

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("MEXTConnector closed source_id={}", self.config.source_id)
