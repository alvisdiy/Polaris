"""Clean raw HTML into processable text.

Two outputs, deliberately separated:

- ``clean_text``  — trafilatura main content. What extraction reads.
- ``page_title`` / ``headings`` / ``anchors`` — structural context.

M8 extracted names like ``Number of Scholarship`` because trafilatura's
main text is prose with no indication of what the page was *about*. The
M9 quality gate needs that indication: a candidate string found in the
page title or an h1 is evidence; the same string in body prose is not.
Discarding structure at cleaning time made that evidence unrecoverable
downstream, so the cleaner keeps it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from services.ingestion.loader import LoadedDocument
from services.ingestion.untrusted import strip_invisible_content

_MAX_HEADINGS = 40
_MAX_ANCHORS = 200


class AnchorLink(BaseModel):
    """Visible anchor label and its href, kept as source evidence."""

    model_config = ConfigDict(frozen=True)

    text: str
    href: str


class CleanedDocument(BaseModel):
    """Cleaned text plus the page structure needed to judge an extraction."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    source_id: str
    source_url: str
    content_type: str
    clean_text: str

    page_title: str = ""
    headings: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    anchor_links: list[AnchorLink] = Field(default_factory=list)
    looks_like_index: bool = False

    # Injection markers found in parts of the page a reader never sees —
    # comments, <script>, <style>. Recorded rather than acted on: the text is
    # already excluded from `clean_text`, and "this page tried to address the
    # extractor" is evidence worth keeping next to the extraction.
    hidden_instruction_markers: list[str] = Field(default_factory=list)


def _extract_structure(html: str, source_url: str) -> tuple[str, list[str], list[str], list[AnchorLink]]:
    """Pull title, headings, anchor labels, and resolved hrefs out of HTML."""
    try:
        from urllib.parse import urldefrag, urljoin, urlsplit

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001 — malformed HTML must not break cleaning
        return "", [], [], []

    title = ""
    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.split())[:300]

    headings: list[str] = []
    for level in ("h1", "h2", "h3"):
        for tag in soup.find_all(level):
            text = " ".join(tag.get_text(" ", strip=True).split())[:300]
            if text:
                headings.append(text)

    anchors: list[str] = []
    anchor_links: list[AnchorLink] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        text = " ".join(tag.get_text(" ", strip=True).split())[:200]
        href = urldefrag(urljoin(source_url, str(tag.get("href", "")).strip()))[0]
        if urlsplit(href).scheme not in {"http", "https"}:
            continue
        if text and text not in seen:
            seen.add(text)
            anchors.append(text)
        if text and len(anchor_links) < _MAX_ANCHORS:
            anchor_links.append(AnchorLink(text=text, href=href[:2048]))

    return title, headings[:_MAX_HEADINGS], anchors[:_MAX_ANCHORS], anchor_links


def _looks_like_index(headings: list[str], anchors: list[str], text: str) -> bool:
    """Heuristic: does this page list many things rather than describe one?

    A scholarship detail page has few links relative to its prose and its
    headings read as a name. An index page has dense link lists and headings
    that read as categories. Used only to cap extraction confidence, never
    to reject a record outright.
    """
    if not text:
        return True
    linky_headings = sum(
        1 for h in headings if h.casefold() in {"scholarships", "scholarship", "programs", "programmes"}
    )
    if linky_headings and len(anchors) > len(headings) * 4:
        return True
    if len(anchors) > 120 and len(text) < 20000:
        return True
    return False


def clean(doc: LoadedDocument) -> CleanedDocument:
    """Extract clean main content plus structural context from raw HTML."""
    page_title, headings, anchors, anchor_links = "", [], [], []
    clean_text = doc.raw_content
    hidden_markers: list[str] = []

    if doc.content_type == "html":
        page_title, headings, anchors, anchor_links = _extract_structure(doc.raw_content, doc.source_url)
        import trafilatura

        # Drop comments and script/style bodies before anything reads the page.
        # They are not content, and text hidden from a reader has no business
        # becoming a scholarship field (M10 untrusted-content boundary).
        visible_html, hidden_markers = strip_invisible_content(doc.raw_content)

        text = trafilatura.extract(
            visible_html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        clean_text = text if text else ""

    return CleanedDocument(
        document_id=doc.document_id,
        source_id=doc.source_id,
        source_url=doc.source_url,
        content_type=doc.content_type,
        clean_text=clean_text,
        page_title=page_title,
        headings=headings,
        anchors=anchors,
        anchor_links=anchor_links,
        looks_like_index=_looks_like_index(headings, anchors, clean_text),
        hidden_instruction_markers=hidden_markers,
    )
