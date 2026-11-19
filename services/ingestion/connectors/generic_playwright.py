"""Generic Playwright connector for JS-rendered scholarship portals.

Uses Playwright for headless browser fetching and link discovery.
Configurable via ConnectorConfig.custom_settings, same as GenericHTTPConnector.
Use this when the target site requires JavaScript rendering.
"""

import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from loguru import logger
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from services.exploration.url_utils import is_detail_record_url
from services.ingestion.connectors.base_connector import (
    BaseConnector,
    ConnectorConfig,
    ConnectorHTTPException,
    ConnectorParsingException,
    ConnectorSecurityException,
    ConnectorTimeoutException,
    FetchResult,
)
from services.ingestion.connectors.generic_connector import (
    DEFAULT_DISCOVERY_KEYWORDS,
    DEFAULT_EXCLUDE_EXTENSIONS,
)
from services.ingestion.robots import RobotsPolicy
from services.ingestion.url_safety import (
    UrlSafetyError,
    validate_external_url,
    validate_redirect_chain,
)

#: A PDF is not a page. When navigation meets one, Chromium starts a download
#: and Playwright raises "Download is starting" — observed on the 2026-10-12
#: JP live run, where every ranked page of two verified sources was a PDF
#: pamphlet and all three fetches died here. PDFs are fetched as bytes through
#: the browser's HTTP request context instead: same cookies, proxy and
#: user-agent, no navigation, and the response can be validated (status,
#: signature, size) before anything is stored.
PDF_URL_SUFFIX = ".pdf"
#: Hard caps. A scholarship pamphlet is a few megabytes; anything larger is a
#: different kind of document and is refused rather than pulled into memory
#: and then into the knowledge base.
DEFAULT_MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_PDF_TEXT_CHARS = 500_000

#: How long to wait for a page's own scripts to finish populating it after
#: ``domcontentloaded``. Many official listings are an empty shell at that
#: point and fetch their rows from a same-origin JSON feed, so the DOM is read
#: too early and the page looks like it has four navigation links and no
#: scholarships. Measured on the 2026-10 run: the University of Tsukuba's
#: scholarship listing held 4 anchors at ``domcontentloaded`` and 1,415
#: after it settled. Bounded, and a page that never idles keeps whatever it
#: rendered rather than failing the fetch.
DEFAULT_RENDER_WAIT_MS = 6000


def _is_pdf_url(url: str) -> bool:
    """Whether the URL path itself names a PDF (query strings ignored)."""
    from urllib.parse import urlparse

    return urlparse(url).path.lower().endswith(PDF_URL_SUFFIX)


def _extract_pdf_text(body: bytes, url: str, source_id) -> str:
    """Extract text from validated PDF bytes.

    Rejects rather than repairs: an encrypted PDF is an access restriction
    and is not bypassed, a malformed one is not a document, and a PDF with
    no extractable text (a scan) cannot be read by the deterministic
    extractor. Each case raises a parsing exception with the reason, so the
    failure is diagnosable instead of surfacing as an empty scholarship.
    """
    from io import BytesIO

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ConnectorParsingException(
            "pypdf is required to acquire PDF documents", source_id=source_id
        ) from exc

    try:
        reader = PdfReader(BytesIO(body))
        if reader.is_encrypted:
            raise ConnectorParsingException(
                f"Encrypted PDF not processed: {url}", source_id=source_id
            )
        parts: list[str] = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            parts.append(page.extract_text() or "")
    except ConnectorParsingException:
        raise
    except Exception as e:
        raise ConnectorParsingException(
            f"Malformed PDF {url}: {e}", source_id=source_id
        ) from e

    text = "\n".join(parts).strip()
    if not text:
        raise ConnectorParsingException(
            f"PDF has no extractable text (scanned document?): {url}",
            source_id=source_id,
        )
    return text[:MAX_PDF_TEXT_CHARS]


class GenericPlaywrightConnector(BaseConnector):
    """Playwright-based connector for JS-rendered scholarship portals."""

    def __init__(self, config: ConnectorConfig) -> None:
        super().__init__(config)
        self._playwright = None
        self._browser = None
        self._context = None
        # M10: the browser is a crawler too. Same robots policy and same URL
        # safety boundary as the HTTP connectors — a JS-rendered portal is not
        # a lower-trust destination.
        self._robots = RobotsPolicy(
            user_agent=(self.config.user_agent or RobotsPolicy().user_agent)
        )

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
        # Before the browser is sent anywhere: the target must be public, and
        # robots must allow it.
        validate_external_url(target_url, resolve_dns=True)
        if not (await self._robots.can_fetch(target_url)).allowed:
            raise ConnectorSecurityException(
                f"robots.txt forbids fetching {target_url}",
                source_id=self.config.source_id,
            )

        start = time.perf_counter()

        if _is_pdf_url(target_url):
            # A direct PDF URL must never reach page.goto: navigation cannot
            # render it and the download it triggers leaves the pipeline with
            # nothing to read.
            return await self._fetch_pdf(target_url, start)

        page = await self._context.new_page()

        try:
            response = await self._navigate(page, target_url)

            if response is None:
                raise ConnectorTimeoutException(
                    f"No response from {target_url}",
                    source_id=self.config.source_id,
                )

            # After: the page may have been redirected, and the redirect target
            # is chosen by the remote host, not by us.
            validate_redirect_chain(str(page.url), [target_url])

            status = response.status

            if status < 200 or status >= 300:
                raise ConnectorHTTPException(
                    f"HTTP {status} fetching {target_url}",
                    status_code=status,
                    source_id=self.config.source_id,
                )

            await self._settle(page)
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
            if "Download is starting" in str(e):
                # The URL did not say ".pdf" but the server answered the
                # navigation with a download anyway (Content-Disposition, or
                # a PDF behind a clean URL). Same validated byte path as a
                # direct PDF URL — and if the payload is not actually a PDF,
                # that is rejected there rather than stored.
                return await self._fetch_pdf(target_url, start)
            if "timeout" in str(e).lower():
                raise ConnectorTimeoutException(str(e), source_id=self.config.source_id)
            raise ConnectorHTTPException(str(e), status_code=500, source_id=self.config.source_id)
        finally:
            await page.close()

    async def _navigate(self, page, url: str):
        """Load a page, tolerating one that never finishes loading.

        ``domcontentloaded`` waits for the document and its blocking
        subresources. Some official sites never get there — a hung font, a
        tracker, a CDN that stalls — and the whole page became an acquisition
        failure: the Kanazawa University announcement timed out at 30s on the
        2026-10 run and the source was recorded as yielding nothing although
        the server had answered in under a second.

        On that timeout only, navigate again with ``wait_until="commit"``,
        which returns as soon as the response starts, and read whatever the
        page rendered. The alternative is keeping a page that exists and that
        passed every safety check, on the grounds that its scripts are slow.
        """
        try:
            return await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.config.timeout * 1000,
            )
        except PlaywrightTimeoutError:
            logger.warning(
                "Navigation to {} did not reach domcontentloaded in {}s; "
                "retrying for the committed response",
                url, self.config.timeout,
            )
            return await page.goto(
                url,
                wait_until="commit",
                timeout=self.config.timeout * 1000,
            )

    async def _settle(self, page) -> None:
        """Give a rendered page a bounded chance to finish building itself.

        ``domcontentloaded`` fires before client-side rendering runs, so a
        page whose content arrives from a JSON feed or a lazy loader is read
        as an empty shell. Waiting for the network to go quiet is what turns
        that shell into the page a reader would see.

        Never raises and never extends the fetch indefinitely: a page that
        polls or streams never goes idle, and that must not turn a successful
        fetch into a timeout.
        """
        wait_ms = int(
            (self.config.custom_settings or {}).get("render_wait_ms", DEFAULT_RENDER_WAIT_MS)
        )
        if wait_ms <= 0:
            return
        try:
            await page.wait_for_load_state("networkidle", timeout=wait_ms)
        except Exception as exc:  # noqa: BLE001 — a busy page is not a failure
            logger.debug("Page did not settle within {}ms: {}", wait_ms, exc)

    async def _fetch_pdf(self, url: str, start: float) -> FetchResult:
        """Fetch a PDF as bytes through the browser's HTTP request context.

        Not a navigation: ``context.request`` performs an ordinary HTTP GET
        with the browser context's cookies, proxy and user-agent, so the
        same URL-safety and robots boundary that guards page fetches guards
        this one. The response is validated before storage — status, then a
        ``%PDF-`` file signature (an HTML error page served with 200 is the
        classic trap), then size — and only then is the text extracted into
        the FetchResult the existing pipeline already understands.
        """
        custom = self.config.custom_settings or {}
        max_bytes = int(custom.get("max_pdf_bytes", DEFAULT_MAX_PDF_BYTES))

        try:
            response = await self._context.request.get(
                url, timeout=self.config.timeout * 1000
            )
        except Exception as e:
            if "timeout" in str(e).lower():
                raise ConnectorTimeoutException(str(e), source_id=self.config.source_id)
            raise ConnectorHTTPException(
                str(e), status_code=502, source_id=self.config.source_id
            )

        status = response.status
        if status < 200 or status >= 300:
            raise ConnectorHTTPException(
                f"HTTP {status} fetching PDF {url}",
                status_code=status,
                source_id=self.config.source_id,
            )

        headers = dict(response.headers)
        # Refuse an oversized body before downloading it when the server says
        # so; the post-download check below covers servers that do not.
        length_header = headers.get("content-length", "")
        if length_header.isdigit() and int(length_header) > max_bytes:
            raise ConnectorHTTPException(
                f"PDF of {length_header} bytes exceeds limit {max_bytes}",
                status_code=413,
                source_id=self.config.source_id,
            )

        final_url = str(response.url)
        # The request context followed redirects without us: the redirect
        # target is chosen by the remote host, so the same chain validation
        # applies as after a navigation.
        try:
            validate_redirect_chain(final_url, [url])
        except UrlSafetyError as exc:
            raise ConnectorSecurityException(
                str(exc), source_id=self.config.source_id
            ) from exc

        body = await response.body()
        if len(body) > max_bytes:
            raise ConnectorParsingException(
                f"PDF of {len(body)} bytes exceeds limit {max_bytes}",
                source_id=self.config.source_id,
            )
        if not body.startswith(b"%PDF-"):
            # Status 200 with an HTML body is an error page, not a document.
            raise ConnectorParsingException(
                f"Response for {url} is not a PDF "
                f"(content-type={headers.get('content-type', 'unset')!r})",
                source_id=self.config.source_id,
            )

        text = _extract_pdf_text(body, url, self.config.source_id)

        elapsed_ms = (time.perf_counter() - start) * 1000
        return FetchResult(
            source_id=self.config.source_id,
            raw_content=text,
            content_type="pdf",
            final_url=final_url,
            response_size=len(body),
            encoding="utf-8",
            status_code=status,
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
            crawl_duration_ms=int(elapsed_ms),
            crawl_time=datetime.now(timezone.utc),
            processing_time_ms=elapsed_ms,
            retry_count=0,
            headers=headers,
        )

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
        keyword heuristic as GenericHTTPConnector. Bare URLs only: callers that
        can use the anchor text that named each link should call
        :meth:`discover_with_context` instead.
        """
        discovered = await self.discover_with_context()
        return [url for url, _anchor in discovered]

    async def discover_with_context(self) -> list[tuple[str, str]]:
        """Discover candidate links together with the anchor text naming them.

        The anchor text is the only signal some pages offer. A query-based
        detail link (``view.do?seq=759978``) says nothing about funding, while
        the label next to it names the scholarship. GenericHTTPConnector has
        read anchor text since M11; this connector read the href alone, so the
        same entry page yielded candidates over HTTP and nothing over
        Playwright. The MOFA Korea entry page has exactly that shape, which is
        what the 2026-10 live run established.

        Returns ``(url, anchor_text)`` pairs so the acquisition policy can rank
        a neutral URL on the evidence that actually describes it. ``discover``
        still returns bare URLs for every existing caller.
        """
        return await self.discover_links_from(str(self.config.url))

    async def discover_links_from(self, url: str) -> list[tuple[str, str]]:
        """Discover ``(url, anchor_text)`` pairs on any page, not just the entry.

        The entry page is where discovery starts, not where it ends. A verified
        source's front page often links only to its own section pages, and the
        programme rows live one level below that — the University of Tsukuba's
        entry page lists four navigation links while the section page it points
        at holds 1,415 programme records. Acquisition can only reach those if
        the connector can be asked to look at a page other than its configured
        entry, which is what this method is for.

        Same boundaries as the entry page: URL safety, robots, redirect
        validation, and the anchor-text-aware extraction.
        """
        if not self._context:
            raise ConnectorSecurityException(
                "Not connected. Call connect() first.",
                source_id=self.config.source_id,
            )

        logger.info("GenericPlaywrightConnector discovering URLs from {}", url)

        # M11: the browser is a crawler. Discovery used to navigate with no
        # robots check and no URL-safety validation, which made it the one
        # path that would read a page `fetch()` would refuse. The same boundary
        # now applies before navigation, not only after it.
        validate_external_url(url, resolve_dns=True)
        if not (await self._robots.can_fetch(url)).allowed:
            logger.warning("robots.txt forbids discovering {}", url)
            return []

        page = await self._context.new_page()
        try:
            response = await self._navigate(page, url)
            if response is None or response.status < 200 or response.status >= 300:
                logger.warning("Discovery page load failed")
                return []

            # The rows a listing shows are frequently rendered after the
            # document loads. Reading the DOM before it settles is how a
            # listing page with 1,415 programmes reports four links.
            await self._settle(page)
            html = await page.content()
            # After navigation the page may have been redirected, and the
            # redirect target is chosen by the remote host, not by us.
            validate_redirect_chain(str(page.url), [url])
            discovered = self._extract_candidate_links_with_context(html, url)
            logger.info(
                "GenericPlaywrightConnector discovered {} candidate URLs",
                len(discovered),
            )
            return discovered

        except Exception as e:
            logger.warning("GenericPlaywrightConnector discovery error: {}", e)
            return []
        finally:
            await page.close()

    def _extract_candidate_links(self, html: str, base_url: str) -> list[str]:
        """Candidate URLs on the page, using the same logic as GenericHTTPConnector."""
        return [
            url for url, _anchor in self._extract_candidate_links_with_context(html, base_url)
        ]

    def _extract_candidate_links_with_context(
        self, html: str, base_url: str
    ) -> list[tuple[str, str]]:
        """Candidate links paired with the anchor text that named each one.

        Two things this connector was missing that GenericHTTPConnector already
        does:

        1. The href was scraped with a regular expression, so any anchor whose
           attributes contained a quote or an entity was either mangled or lost.
           The DOM is parsed instead, which is what the connector actually has.
        2. Keyword matching read the URL alone. An award's URL often says
           nothing about funding — ``/edge-programme``,
           ``/tp-eng-scholars-2026.html``, ``view.do?seq=759978`` — while the
           link's own label names the scholarship. The anchor text is read too,
           and the pair is returned so the acquisition policy can weigh a
           neutral URL on the evidence that describes it.

        Fragments are stripped and duplicates collapse to one entry.
        """
        custom = self.config.custom_settings or {}
        custom_pattern = custom.get("url_pattern")
        exclude_patterns = custom.get("exclude_patterns", [])
        keywords = [str(kw).lower() for kw in custom.get("keywords", DEFAULT_DISCOVERY_KEYWORDS)]
        allow_subdomains = custom.get("allow_subdomains", True)

        base_domain = urlparse(base_url).netloc.lower()

        seen: set[str] = set()
        candidates: list[tuple[str, str]] = []

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

            label = " ".join(anchor.get_text(" ", strip=True).split())
            if not custom_pattern:
                url_signal = (parsed.path + "?" + parsed.query).lower()
                if not (
                    any(kw in url_signal for kw in keywords)
                    or any(kw in label.lower() for kw in keywords)
                    # A record URL says nothing about its subject: `/pg/2026917.html`
                    # and `view.do?seq=759978` name no funding at all, while the
                    # anchor beside them is a foundation's name in Japanese or
                    # Korean. The keyword gate dropped all 1,415 of Tsukuba's
                    # programme links and every MOFA board link for that reason.
                    # Admission only queues the links for classification; the
                    # classifier still decides what they are.
                    or is_detail_record_url(full_url)
                ):
                    continue
            elif not re.search(custom_pattern, full_url, re.IGNORECASE):
                continue

            normalized = full_url.split("#")[0]
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append((normalized, label))

        return candidates


# ponytail: _extract_candidate_links duplicates GenericHTTPConnector.extract_candidate_links.
# Extract to shared function when a third connector needs the same logic.
