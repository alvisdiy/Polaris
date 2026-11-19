import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from services.ingestion.connectors.base_connector import BaseConnector, ConnectorConfig, FetchResult
from services.ingestion.fetch_safety import SafeFetch
from services.ingestion.robots import RobotsPolicy

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
        """Same-site links on the entry page that name a funding opportunity.

        M11. Two defects in the previous version:

        1. It fetched the entry page with ``self.client.get`` directly, which
           bypasses SafeFetch. Discovery was therefore the one path that did
           not honour robots.txt or the URL-safety boundary — the crawler
           reading a page it would have refused to fetch. It now goes through
           the same ``_safe()`` path as ``fetch``.
        2. It returned ``[entry_url]`` on failure, which handed the entry
           page to the extractor as though it were a scholarship link. A
           failed discovery now returns nothing, and says why.
        """
        if not self.client:
            await self.connect()

        entry_url = str(self.config.url)
        try:
            response = await self._safe().get(entry_url)
            response.raise_for_status()
        except Exception as e:
            logger.warning("Generic discovery failed for {}: {}", entry_url, e)
            return []

        custom = self.config.custom_settings or {}
        if custom.get("url_pattern"):
            return self.extract_candidate_links(response.text, entry_url)

        # An award's URL often says nothing about funding — `/edge-programme`,
        # `/nus-merit-scholarship` aside, `/tp-eng-scholars-2026.html`. The
        # anchor text is the signal that is actually about the scholarship, so
        # it is read as well as the href.
        keywords = [kw.lower() for kw in custom.get("keywords", DEFAULT_DISCOVERY_KEYWORDS)]
        allow_subdomains = custom.get("allow_subdomains", True)
        base_domain = urlparse(entry_url).netloc.lower()
        base_root = _root_domain(base_domain)

        seen: set[str] = set()
        discovered: List[str] = []
        for anchor in BeautifulSoup(response.text, "html.parser").find_all("a", href=True):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            full_url = urljoin(entry_url, href)
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

            label = " ".join(anchor.get_text(" ", strip=True).split()).lower()
            url_signal = (parsed.path + "?" + parsed.query).lower()
            if not (
                any(kw in url_signal for kw in keywords)
                or any(kw in label for kw in keywords)
            ):
                continue

            normalized = full_url.split("#")[0].rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            discovered.append(normalized)
        return discovered

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
            crawl_duration_ms=0,
            processing_time_ms=0.0,
            retry_count=0,
            headers=dict(response.headers),
        )
