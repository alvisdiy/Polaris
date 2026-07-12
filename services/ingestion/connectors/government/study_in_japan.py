import time
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from services.ingestion.connectors.base_connector import (
    BaseConnector,
    ConnectorConfig,
    FetchResult,
    ConnectorTimeoutException,
    ConnectorHTTPException,
    ConnectorSecurityException,
)


class StudyInJapanConnector(BaseConnector):
    """Playwright connector for Study in Japan (MEXT) official website."""

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._playwright = None
        self._browser = None
        self._context = None

    async def connect(self) -> None:
        """Initialize Playwright and launch a headless Chromium browser."""
        try:
            self._playwright = await async_playwright().start()

            launch_args = []
            if self.config.proxy:
                launch_args.append(f"--proxy-server={self.config.proxy}")

            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=launch_args,
            )

            context_args = {}
            if self.config.user_agent:
                context_args["user_agent"] = self.config.user_agent
            if self.config.headers:
                context_args["extra_http_headers"] = self.config.headers

            self._context = await self._browser.new_context(**context_args)
        except Exception as e:
            await self.close()
            raise ConnectorSecurityException(
                f"Failed to launch browser: {e}",
                source_id=self.config.source_id,
            )

    async def fetch(self) -> FetchResult:
        """Navigate to the configured URL and return the page HTML."""
        if not self._context:
            raise ConnectorSecurityException(
                "Not connected. Call connect() first.",
                source_id=self.config.source_id,
            )

        page = await self._context.new_page()
        start = time.perf_counter()
        url = str(self.config.url)

        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.config.timeout * 1000,
            )

            if response is None:
                raise ConnectorTimeoutException(
                    f"No response from {url}",
                    source_id=self.config.source_id,
                )

            status = response.status

            if status < 200 or status >= 300:
                raise ConnectorHTTPException(
                    f"HTTP {status} fetching {url}",
                    status_code=status,
                    source_id=self.config.source_id,
                )

            raw_content = await page.content()
            headers = dict(response.headers)
            encoding = "utf-8"
            ct = headers.get("content-type", "")
            if "charset=" in ct:
                encoding = ct.split("charset=")[-1].strip()

            elapsed_ms = (time.perf_counter() - start) * 1000

            return FetchResult(
                source_id=self.config.source_id,
                raw_content=raw_content,
                content_type="html",
                final_url=response.url,
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

        except (ConnectorTimeoutException, ConnectorHTTPException, ConnectorSecurityException):
            raise
        except Exception as e:
            if "timeout" in str(e).lower():
                raise ConnectorTimeoutException(str(e), source_id=self.config.source_id)
            raise ConnectorHTTPException(str(e), status_code=500, source_id=self.config.source_id)
        finally:
            await page.close()

    async def close(self) -> None:
        """Close browser context, browser, and Playwright instance."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
