import logging
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from services.ingestion.connectors.base_connector import BaseConnector, ConnectorConfig, FetchResult
from services.ingestion.fetch_safety import SafeFetch
from services.ingestion.robots import RobotsPolicy

logger = logging.getLogger(__name__)


class MEXTConnector(BaseConnector):
    """Connector for Study in Japan (MEXT) scholarship portal."""

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.client: Optional[httpx.AsyncClient] = None
        # M10: robots policy and URL safety are applied per request through
        # SafeFetch, not here, so every connector enforces the same rules.
        self.robots = RobotsPolicy(
            user_agent=(self.config.user_agent or RobotsPolicy().user_agent)
        )

    def _safe(self) -> SafeFetch:
        return SafeFetch(
            self.client,
            max_retries=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            robots=self.robots,
        )

    async def connect(self) -> bool:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=self.config.timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            follow_redirects=True,
        )
        return True

    async def close(self) -> None:
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def discover(self) -> List[str]:
        """Discover MEXT scholarship links from study in japan page."""
        if not self.client:
            await self.connect()

        try:
            response = await self._safe().get(str(self.config.url))
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Simple discovery logic looking for scholarship links
            links = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "scholarship" in href.lower() or "mext" in href.lower() or "planning/about-scholarship" in href:
                    full_url = urljoin(str(self.config.url), href)
                    links.append(full_url)

            # Ensure unique
            unique = list(set(links))
            return unique
        except Exception as e:
            logger.warning("MEXT discovery failed for %s: %s", str(self.config.url), e)
            return []

    # Compatibility alias for scholarship-first discovery interface
    def discover_scholarship_urls(self) -> List[str]:
        """Alias to maintain backward compatibility with older discovery method name."""
        return self.discover()

    async def fetch(self, url: str) -> FetchResult:
        """Fetch content from MEXT page."""
        if not self.client:
            await self.connect()

        response = await self._safe().get(url)
        response.raise_for_status()

        return FetchResult(
            source_id=self.config.source_id,
            raw_content=response.text,
            content_type="html",
            final_url=str(response.url),
            response_size=len(response.content),
            encoding=response.encoding,
            status_code=response.status_code,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            crawl_duration_ms=0,  # Would need timing
            crawl_time=datetime.now(timezone.utc),
            processing_time_ms=0.0,
            retry_count=0,
            headers=dict(response.headers),
        )
