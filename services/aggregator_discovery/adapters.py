"""Bounded feed/HTML article discovery for scholarship aggregation sites.

This module discovers article URLs only. It deliberately does not fetch article
pages or persist scholarships; those steps require the later verification and
provenance stages.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup

from services.exploration.url_utils import normalize_url

_NON_ARTICLE_SEGMENTS = {
    "about",
    "contact",
    "category",
    "tag",
    "author",
    "page",
    "feed",
    "search",
    "privacy-policy",
    "terms-and-conditions",
    "scholarships",
    "fully-funded-scholarships",
    "undergraduate-scholarships",
    "masters-scholarships",
    "phd-scholarships",
    "fellowships",
}
_YEAR_OR_ARTICLE = re.compile(r"(?:19|20)\d{2}|scholarship|fellowship|bursar|grant|studentship", re.I)
_NON_SCHOLARSHIP_TERMS = re.compile(r"\b(internship|online course|visa|conference|job vacancy|webinar)\b", re.I)


@dataclass(frozen=True)
class AggregatorSource:
    id: str
    name: str
    base_url: str
    discovery_urls: tuple[str, ...]
    discovery_mode: str = "html"
    max_pages: int = 3


@dataclass(frozen=True)
class AggregatorCandidate:
    source_id: str
    url: str
    canonical_url: str
    title: str
    discovered_from: str
    discovery_method: str
    page_intent: str
    listing_verdict: str


def load_aggregator_sources(path: str | Path | None = None) -> tuple[AggregatorSource, ...]:
    """Load bounded source configuration without a database or country context."""
    config_path = Path(path) if path else Path(__file__).resolve().parents[2] / "configs" / "aggregators.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    result = []
    for item in payload.get("sources", []):
        mode = item.get("discovery_mode", "html")
        max_pages = int(item.get("max_pages", 3))
        if mode not in {"html", "rss"}:
            raise ValueError(f"Unsupported aggregator discovery mode: {mode}")
        if max_pages < 1 or max_pages > 20:
            raise ValueError("max_pages must be between 1 and 20")
        discovery_urls = tuple(str(url) for url in item["discovery_urls"])
        if not discovery_urls:
            raise ValueError(f"Aggregator {item['id']} must define at least one discovery URL")
        result.append(
            AggregatorSource(
                id=str(item["id"]),
                name=str(item["name"]),
                base_url=str(item["base_url"]),
                discovery_urls=discovery_urls,
                discovery_mode=mode,
                max_pages=max_pages,
            )
        )
    if not result:
        raise ValueError("Aggregator configuration contains no sources")
    return tuple(result)


def _is_candidate_url(url: str, source: AggregatorSource) -> bool:
    parts = urlsplit(url)
    base_host = (urlsplit(source.base_url).hostname or "").removeprefix("www.").lower()
    target_host = (parts.hostname or "").removeprefix("www.").lower()
    if parts.scheme not in {"http", "https"} or target_host != base_host:
        return False
    segments = [segment.casefold() for segment in parts.path.split("/") if segment]
    if not segments or any(segment in _NON_ARTICLE_SEGMENTS for segment in segments):
        return False
    if any(segment.isdigit() for segment in segments):
        return False
    return bool(_YEAR_OR_ARTICLE.search(parts.path))


def _candidate(source: AggregatorSource, url: str, title: str, origin: str, method: str) -> AggregatorCandidate | None:
    absolute = urljoin(origin, url.strip())
    if not _is_candidate_url(absolute, source):
        return None
    canonical = normalize_url(absolute)
    if not canonical:
        return None
    if _NON_SCHOLARSHIP_TERMS.search(title):
        return None
    from services.exploration.listing_guard import ListingVerdict, classify_listing_page
    from services.exploration.page_intent import PageIntent, classify_page_intent

    intent = classify_page_intent(url=absolute, page_title=title, headings=[title] if title else [], text="")
    listing = classify_listing_page(
        page_title=title,
        headings=[title] if title else [],
        text="",
        intent=intent,
    )
    # Discovery metadata cannot settle every article; retain UNKNOWN for the
    # later fetched-page classifier. Definite collection/listing URLs are not
    # articles and must not enter the candidate set.
    title_is_explicit_list = bool(
        re.search(
            r"\b(?:top\s+\d+|\d+\s+(?:fully funded\s+)?scholarships|list of scholarships|scholarship opportunities)\b",
            title,
            re.I,
        )
    )
    if title_is_explicit_list and intent.intent in {PageIntent.SCHOLARSHIP_INDEX, PageIntent.SCHOLARSHIP_OVERVIEW}:
        return None
    # The listing guard may inherit a high-confidence verdict from PageIntent.
    # With only an archive anchor available, that can misread a single award
    # title as an overview. Use the guard's structural listing evidence only;
    # the fetched article will receive the full guard in the later pipeline.
    structural_listing_signals = {
        "count_heading",
        "listing_construction_heading",
        "repeated_award_headings",
        "programme_link_spike",
        "metric_heading_no_opportunity_claim",
    }
    if listing.verdict == ListingVerdict.HIGH_CONFIDENCE_LISTING and any(
        signal in structural_listing_signals for signal in listing.signals
    ):
        return None
    return AggregatorCandidate(
        source_id=source.id,
        url=absolute.split("#", 1)[0],
        canonical_url=canonical,
        title=" ".join(title.split())[:300],
        discovered_from=origin,
        discovery_method=method,
        page_intent=intent.intent,
        listing_verdict=listing.verdict,
    )


def _pagination_urls(html: str, page_url: str, source: AggregatorSource) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    result: list[str] = []
    for anchor in soup.find_all("a", href=True):
        label = " ".join(anchor.get_text(" ", strip=True).split()).casefold()
        href = urljoin(page_url, anchor["href"])
        path = urlsplit(href).path.casefold()
        if (
            anchor.get("rel") == ["next"]
            or label in {"next", "older posts", "›", "»"}
            or re.search(r"/page/\d+/?$", path)
        ):
            if _is_same_site(href, source) and normalize_url(href) != normalize_url(page_url):
                result.append(href)
    return result


def _is_same_site(url: str, source: AggregatorSource) -> bool:
    base_host = (urlsplit(source.base_url).hostname or "").removeprefix("www.").lower()
    host = (urlsplit(url).hostname or "").removeprefix("www.").lower()
    return host == base_host


def discover_html_candidates(
    source: AggregatorSource,
    pages: dict[str, str],
) -> list[AggregatorCandidate]:
    """Parse supplied archive HTML pages; caller owns safe, robots-aware fetching.

    Pagination is followed only when its page HTML is already present in
    ``pages``. This keeps network policy and the run's page budget in the caller.
    """
    found: dict[str, AggregatorCandidate] = {}
    for page_url, html in pages.items():
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            title = " ".join(anchor.get_text(" ", strip=True).split())
            candidate = _candidate(source, anchor["href"], title, page_url, "html_archive")
            if candidate:
                found.setdefault(candidate.canonical_url, candidate)
    return list(found.values())


async def discover_html_source(source: AggregatorSource, fetch_page) -> list[AggregatorCandidate]:
    """Fetch configured HTML archives with a hard page cap and parse candidates.

    ``fetch_page`` is injected so production wiring can use Polaris' guarded
    connector and tests can use local fixtures. It must enforce URL safety,
    robots, redirect checks, and host pacing; this function never makes raw
    network requests itself.
    """
    queue = deque(source.discovery_urls)
    visited: set[str] = set()
    pages: dict[str, str] = {}
    while queue and len(visited) < source.max_pages:
        page_url = queue.popleft()
        key = normalize_url(page_url)
        if not key or key in visited:
            continue
        visited.add(key)
        body = fetch_page(page_url)
        if inspect.isawaitable(body):
            body = await body
        if not isinstance(body, str):
            raise TypeError("fetch_page must return HTML text")
        pages[page_url] = body
        queue.extend(url for url in _pagination_urls(body, page_url, source) if normalize_url(url) not in visited)
    return discover_html_candidates(source, pages)


async def discover_configured_source(source: AggregatorSource) -> list[AggregatorCandidate]:
    """Run configured HTML discovery through Polaris' guarded Playwright connector.

    The connector UUID is local to this read-only crawl; no database row,
    country, or provider is required. Requests are capped by ``max_pages`` and
    spaced by one second per host.
    """
    if source.discovery_mode != "html":
        raise ValueError("Configured connector runner currently supports HTML sources only")
    from services.ingestion.connectors.base_connector import ConnectorConfig
    from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector

    if not source.discovery_urls:
        raise ValueError("HTML source has no discovery URL")
    connector = GenericPlaywrightConnector(
        ConnectorConfig(
            source_id=uuid4(),
            url=source.discovery_urls[0],
            timeout=20,
            max_retries=1,
            user_agent="PolarisBot/0.1 (scholarship discovery)",
        )
    )
    last_request_at: float | None = None

    async def fetch_page(url: str) -> str:
        nonlocal last_request_at
        loop = asyncio.get_running_loop()
        if last_request_at is not None:
            remaining = 1.0 - (loop.time() - last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        last_request_at = loop.time()
        fetched = await connector.fetch(url)
        if fetched.content_type != "html":
            return ""
        return fetched.raw_content

    try:
        await connector.connect()
        return await discover_html_source(source, fetch_page)
    finally:
        await connector.close()


def discover_rss_candidates(source: AggregatorSource, xml_body: str, feed_url: str) -> list[AggregatorCandidate]:
    """Parse RSS 2.0 or Atom entries while preserving their article URLs."""
    try:
        root = ET.fromstring(xml_body)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid RSS/Atom document at {feed_url}") from exc
    entries = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] in {"item", "entry"}]
    found: dict[str, AggregatorCandidate] = {}
    for entry in entries:
        title = next((node.text or "" for node in entry if node.tag.rsplit("}", 1)[-1] == "title"), "")
        link = ""
        for node in entry:
            if node.tag.rsplit("}", 1)[-1] != "link":
                continue
            link = node.attrib.get("href", "") or (node.text or "")
            if link:
                break
        candidate = _candidate(source, link, title, feed_url, "rss") if link else None
        if candidate:
            found.setdefault(candidate.canonical_url, candidate)
    return list(found.values())


def archive_page_intent(page_url: str, html: str):
    """Return the existing intent and listing verdict for an archive surface."""
    from services.exploration.listing_guard import classify_listing_page
    from services.exploration.page_intent import classify_page_intent

    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    headings = [" ".join(node.get_text(" ", strip=True).split()) for node in soup.select("h1, h2, h3")]
    anchors = [" ".join(node.get_text(" ", strip=True).split()) for node in soup.find_all("a", href=True)]
    text = " ".join(soup.stripped_strings)[:20000]
    intent = classify_page_intent(url=page_url, page_title=title, headings=headings, anchors=anchors, text=text)
    listing = classify_listing_page(page_title=title, headings=headings, anchors=anchors, text=text, intent=intent)
    return intent, listing
