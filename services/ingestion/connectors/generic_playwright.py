"""Generic Playwright connector for JS-rendered scholarship portals.

Uses Playwright for headless browser fetching and link discovery.
Configurable via ConnectorConfig.custom_settings, same as GenericHTTPConnector.
Use this when the target site requires JavaScript rendering.
"""

import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from loguru import logger
from playwright.async_api import async_playwright

from services.ingestion.connectors.base_connector import (
    BaseConnector,
    ConnectorConfig,
    ConnectorHTTPException,
    ConnectorSecurityException,
    ConnectorTimeoutException,
    FetchResult,
)
from services.ingestion.connectors.generic_connector import (
    DEFAULT_DISCOVERY_KEYWORDS,
    DEFAULT_EXCLUDE_EXTENSIONS,
)


class GenericPlaywrightConnector(BaseConnector):
    """Playwright-based connector for JS-rendered scholarship portals."""

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._playwright = None
        self._browser = None
        self._context = None

    async def connect(self) -> None:
        """Initialize Playwright and launch a headless Chromium browser."""
        logger.info("GenericPlaywrightConnector connecting source_id={}", self.config.source_id)
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
            else:
                context_args["user_agent"] = "PolarisBot/0.1 (Scholarship Intelligence Platform)"
            if self.config.headers:
                context_args["extra_http_headers"] = self.config.headers

            self._context = await self._browser.new_context(**context_args)
        except Exception as e:
            await self.close()
            raise ConnectorSecurityException(
                f"Failed to launch browser: {e}",
                source_id=self.config.source_id,
            )

    async def fetch(self, url: str | None = None) -> FetchResult:
        """Navigate to URL and return the fully rendered page HTML."""
        if not self._context:
            raise ConnectorSecurityException(
                "Not connected. Call connect() first.",
                source_id=self.config.source_id,
            )

        target_url = url or str(self.config.url)
        page = await self._context.new_page()
        start = time.perf_counter()

        try:
            response = await page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=self.config.timeout * 1000,
            )

            if response is None:
                raise ConnectorTimeoutException(
                    f"No response from {target_url}",
                    source_id=self.config.source_id,
                )

            status = response.status

            if status < 200 or status >= 300:
                raise ConnectorHTTPException(
                    f"HTTP {status} fetching {target_url}",
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
        logger.info("GenericPlaywrightConnector closed source_id={}", self.config.source_id)

    async def discover(self) -> list[str]:
        """Discover scholarship URLs from the entry page using Playwright.

        Renders the page with JS, then extracts links using the same
        keyword heuristic as GenericHTTPConnector.
        """
        if not self._context:
            raise ConnectorSecurityException(
                "Not connected. Call connect() first.",
                source_id=self.config.source_id,
            )

        entry_url = str(self.config.url)
        logger.info("GenericPlaywrightConnector discovering URLs from {}", entry_url)

        page = await self._context.new_page()
        try:
            response = await page.goto(
                entry_url,
                wait_until="domcontentloaded",
                timeout=self.config.timeout * 1000,
            )
            if response is None or response.status < 200 or response.status >= 300:
                logger.warning("Discovery page load failed")
                return []

            html = await page.content()
            discovered = self._extract_candidate_links(html, entry_url)
            logger.info("GenericPlaywrightConnector discovered {} candidate URLs", len(discovered))
            return discovered

        except Exception as e:
            logger.warning("GenericPlaywrightConnector discovery error: {}", e)
            return []
        finally:
            await page.close()

    def _extract_candidate_links(self, html: str, base_url: str) -> list[str]:
        """Extract candidate links using the same logic as GenericHTTPConnector."""
        custom = self.config.custom_settings or {}
        custom_pattern = custom.get("url_pattern")
        exclude_patterns = custom.get("exclude_patterns", [])
        keywords = custom.get("keywords", DEFAULT_DISCOVERY_KEYWORDS)
        allow_subdomains = custom.get("allow_subdomains", True)

        base_parsed = urlparse(base_url)
        base_domain = base_parsed.netloc.lower()

        hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)

        candidates: list[str] = []
        for href in hrefs:
            href_clean = href.strip()
            if not href_clean or href_clean.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            full_url = urljoin(base_url, href_clean)
            parsed = urlparse(full_url)
            target_domain = parsed.netloc.lower()

            if not target_domain:
                continue
            if allow_subdomains:
                if not (target_domain == base_domain or target_domain.endswith("." + base_domain)):
                    continue
            else:
                if target_domain != base_domain:
                    continue

            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in DEFAULT_EXCLUDE_EXTENSIONS):
                continue

            if any(re.search(ex, full_url, re.IGNORECASE) for ex in exclude_patterns):
                continue

            if custom_pattern:
                if re.search(custom_pattern, full_url, re.IGNORECASE):
                    candidates.append(full_url)
            else:
                url_to_check = (parsed.path + "?" + parsed.query).lower()
                if any(kw.lower() in url_to_check for kw in keywords):
                    candidates.append(full_url)

        seen = set()
        unique = []
        for url in candidates:
            norm = url.split("#")[0]
            if norm not in seen:
                seen.add(norm)
                unique.append(norm)

        return unique


# ponytail: _extract_candidate_links duplicates GenericHTTPConnector.extract_candidate_links.
# Extract to shared function when a third connector needs the same logic.
