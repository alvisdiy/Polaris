import asyncio
import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from services.ingestion.connectors.base_connector import BaseConnector, ConnectorConfig, FetchResult

logger = logging.getLogger(__name__)

# Discovery configuration constants
# Localized terms matter here: discovery runs against national portals whose
# paths are not written in English (stipendium/bourse/beasiswa/beca).
DEFAULT_DISCOVERY_KEYWORDS = [
    "scholarship", "grant", "fellowship", "funding",
    "stipendium", "bourse", "beasiswa", "beca", "bolsa",
]
DEFAULT_EXCLUDE_EXTENSIONS = [
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
    ".css", ".js", ".ico", ".woff", ".woff2", ".ttf",
    ".zip", ".rar", ".tar", ".gz",
]


def _root_domain(host: str) -> str:
    """Approximate registrable domain: last two labels.

    Deliberately local and simple. Multi-part public suffixes (.co.uk, .ac.jp)
    are not resolved here.
    """
    labels = [label for label in (host or "").lower().split(".") if label]
    return ".".join(labels[-2:]) if len(labels) >= 2 else (labels[-1] if labels else "")


class GenericHTTPConnector(BaseConnector):
    """Generic HTTP connector using httpx and BeautifulSoup."""

    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> bool:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=self.config.timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
        """Discover links ending in .pdf or .html or matching scholarship keywords."""
        if not self.client:
            await self.connect()

        try:
            response = await self.client.get(str(self.config.url))
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            discovered = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if any(kw in href.lower() for kw in ["scholarship", "grant", "fellowship", "funding"]):
                    full_url = urljoin(str(self.config.url), href)
                    discovered.append(full_url.rstrip("/"))

            unique = list(set(discovered))
            if not unique:
                unique = [str(self.config.url)]
            return unique
        except Exception as e:
            logger.error(f"Error discovering generic URLs: {e}")
            return [str(self.config.url)]

    # Compatibility alias for scholarship-first discovery interface
    def discover_scholarship_urls(self) -> List[str]:
        """Alias to maintain backward compatibility with older discovery method name."""
        return self.discover()

    def extract_candidate_links(self, html: str, base_url: str) -> List[str]:
        """Extract same-site candidate links that look like scholarship pages.

        Configuration via ``config.custom_settings``:

        - ``url_pattern``: regex that replaces keyword matching when set
        - ``keywords``: overrides ``DEFAULT_DISCOVERY_KEYWORDS``
        - ``exclude_patterns``: regexes; any match drops the URL
        - ``allow_subdomains``: sibling subdomains of the base domain count as
          same-site (default True). With it off, only the exact host is kept.

        Fragments are stripped and duplicates collapse to one entry.
        """
        custom = self.config.custom_settings or {}
        custom_pattern = custom.get("url_pattern")
        exclude_patterns = custom.get("exclude_patterns", [])
        keywords = custom.get("keywords", DEFAULT_DISCOVERY_KEYWORDS)
        allow_subdomains = custom.get("allow_subdomains", True)

        base_domain = urlparse(base_url).netloc.lower()
        base_root = _root_domain(base_domain)

        seen: set[str] = set()
        candidates: List[str] = []

        for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            target_domain = parsed.netloc.lower()
            if not target_domain:
                continue

            if allow_subdomains:
                if _root_domain(target_domain) != base_root:
                    continue
            elif target_domain != base_domain:
                continue

            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in DEFAULT_EXCLUDE_EXTENSIONS):
                continue
            if any(re.search(pattern, full_url, re.IGNORECASE) for pattern in exclude_patterns):
                continue

            if custom_pattern:
                if not re.search(custom_pattern, full_url, re.IGNORECASE):
                    continue
            else:
                target = (parsed.path + "?" + parsed.query).lower()
                if not any(keyword.lower() in target for keyword in keywords):
                    continue

            normalized = full_url.split("#")[0]
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(normalized)

        return candidates

    async def fetch(self, url: str) -> FetchResult:
        """Fetch content from target URL."""
        if not self.client:
            await self.connect()

        response = await self.client.get(url)
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
            crawl_duration_ms=0,
            processing_time_ms=0.0,
            retry_count=0,
            headers=dict(response.headers),
        )
