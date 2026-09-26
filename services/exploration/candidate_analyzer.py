"""CandidateAnalyzer — fetch once, extract the feature set everything
downstream consumes (classifier, resolvers, link expansion).

Fetch strategy: httpx first (fast, cheap); Playwright fallback when the HTTP
fetch yields JS-gated content (small HTML with little text). Respects
robots.txt, per-domain delay, and timeouts.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from loguru import logger

from services.exploration.url_utils import domain_of

USER_AGENT = "PolarisBot/0.2 (+https://polaris.example; discovery research)"

_SKIP_PREFIXES = ("#", "javascript:", "mailto:", "tel:", "data:")
_BINARY_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".zip", ".pdf",
)

# robots.txt cache: domain → (allow_all, disallow_paths)
_robots_cache: dict[str, tuple[bool, list[str]]] = {}
_domain_locks: dict[str, asyncio.Lock] = {}
_last_fetch_at: dict[str, float] = {}


@dataclass
class PageLink:
    url: str
    anchor_text: str = ""
    title: str = ""


@dataclass
class AnalyzedCandidate:
    url: str
    final_url: str = ""
    status_code: int = 0
    fetched: bool = False
    error: str | None = None
    title: str = ""
    meta_description: str = ""
    headings: list[str] = field(default_factory=list)
    main_text: str = ""
    structured_data: list[dict] = field(default_factory=list)
    org_hints: list[str] = field(default_factory=list)
    links: list[PageLink] = field(default_factory=list)


class _RobotRules:
    """Minimal robots.txt compliance (allow-all on absence/parse failure)."""

    @staticmethod
    async def allowed(client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain not in _robots_cache:
            allow_all, disallows = True, []
            try:
                resp = await client.get(f"{parsed.scheme}://{domain}/robots.txt")
                if resp.status_code == 200 and resp.text:
                    allow_all = False
                    for line in resp.text.splitlines():
                        line = line.strip()
                        if line.lower().startswith("user-agent:"):
                            agent = line.split(":", 1)[1].strip().lower()
                        elif line.lower().startswith("disallow:") and agent in ("*",):
                            path = line.split(":", 1)[1].strip()
                            if path:
                                disallows.append(path)
            except Exception:  # noqa: BLE001 — unreachable robots means allow
                pass
            _robots_cache[domain] = (allow_all, disallows)
        allow_all, disallows = _robots_cache[domain]
        if allow_all:
            return True
        path = parsed.path or "/"
        return not any(path.startswith(d) for d in disallows)


async def _respect_domain_delay(domain: str, delay_ms: int) -> None:
    import time

    lock = _domain_locks.setdefault(domain, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        last = _last_fetch_at.get(domain, 0.0)
        wait = delay_ms / 1000.0 - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_fetch_at[domain] = time.monotonic()


class CandidateAnalyzer:
    def __init__(self, per_domain_delay_ms: int = 1500, timeout: int = 20) -> None:
        self.per_domain_delay_ms = per_domain_delay_ms
        self.timeout = timeout

    async def analyze(self, url: str) -> AnalyzedCandidate:
        """Fetch and analyze one candidate URL."""
        result = AnalyzedCandidate(url=url)
        domain = domain_of(url)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                if not await _RobotRules.allowed(client, url):
                    result.error = "robots_disallowed"
                    return result

                await _respect_domain_delay(domain, self.per_domain_delay_ms)
                response = await client.get(url)
                result.status_code = response.status_code
                result.final_url = str(response.url)
                if response.status_code >= 400:
                    result.error = f"http_{response.status_code}"
                    return result

                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text" not in content_type and content_type:
                    result.error = f"unsupported_content_type_{content_type.split(';')[0]}"
                    return result

                html = response.text
                result.fetched = True
                self._extract_features(result, html)
        except Exception as exc:  # noqa: BLE001
            result.error = f"fetch_error: {exc}"[:300]
            logger.debug("Analyzer fetch failed for {}: {}", url, exc)
            return result

        # Playwright fallback for JS-gated pages
        if result.fetched and len(result.main_text) < 200 and self._looks_js_gated(result):
            await self._analyze_with_playwright(result)

        return result

    @staticmethod
    def _looks_js_gated(result: AnalyzedCandidate) -> bool:
        if len(result.links) > 0 or result.structured_data:
            return False
        return len(result.title) > 0 or len(result.headings) == 0

    def _extract_features(self, result: AnalyzedCandidate, html: str) -> None:
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title_tag = soup.find("title")
        result.title = title_tag.get_text(strip=True)[:500] if title_tag else ""

        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            result.meta_description = meta["content"].strip()[:500]

        for level in ("h1", "h2", "h3"):
            for h in soup.find_all(level):
                text = h.get_text(strip=True)
                if text:
                    result.headings.append(text[:300])

        # JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json

                data = json.loads(script.string or "{}")
                items = data if isinstance(data, list) else [data]
                result.structured_data.extend(i for i in items if isinstance(i, dict))
            except Exception:  # noqa: BLE001
                continue

        # Organization hints
        for pattern in (r"(?:©|&copy;|copyright)\s*\d{4}\s*([^<\n\.]{3,80})",):
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                result.org_hints.append(m.group(1).strip()[:120])
        for meta_name in ("og:site_name", "application-name"):
            tag = soup.find("meta", attrs={"property": meta_name}) or soup.find(
                "meta", attrs={"name": meta_name}
            )
            if tag and tag.get("content"):
                result.org_hints.append(tag["content"].strip()[:120])

        # Main text (simple, dependency-light; trafilatura stays in the
        # extraction pipeline)
        text = soup.get_text(separator=" ", strip=True)
        result.main_text = re.sub(r"\s+", " ", text)[:20000]

        # ALL outbound links with anchor/title context (bounded)
        base = result.final_url or result.url
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.lower().startswith(_SKIP_PREFIXES):
                continue
            absolute = urljoin(base, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                continue
            if any(parsed.path.lower().endswith(ext) for ext in _BINARY_EXTENSIONS):
                continue
            key = f"{parsed.netloc}{parsed.path}".rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            anchor = a.get_text(strip=True)[:200]
            title_attr = (a.get("title") or "").strip()[:200]
            result.links.append(PageLink(url=absolute, anchor_text=anchor, title=title_attr))
            if len(result.links) >= 300:
                break

    async def _analyze_with_playwright(self, result: AnalyzedCandidate) -> None:
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(user_agent=USER_AGENT)
                    await page.goto(result.url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                    html = await page.content()
                    result.final_url = page.url
                    result.fetched = True
                    result.error = None
                    self._extract_features(result, html)
                finally:
                    await browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Playwright fallback failed for {}: {}", result.url, exc)
