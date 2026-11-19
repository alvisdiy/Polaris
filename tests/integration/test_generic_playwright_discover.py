"""Regression tests for GenericPlaywrightConnector link discovery.

These own the link-extraction surface for the connector, and they exist because
of one measured defect: the keyword filter read the href and nothing else, so a
board page whose entries are opaque query URLs (``view.do?seq=759978``) was
discovered as zero candidates no matter how plainly the anchor text named the
scholarship. ``GenericHTTPConnector`` has read anchor text since M11; this
connector did not, so the same page yielded candidates over one connector and
none over the other.

They deliberately do not require Playwright. ``_extract_candidate_links`` is
pure DOM/text extraction over an HTML string, which is what the live browser
path produces as its input once the page has rendered.

The expectations below are the measured behaviour of the corrected extraction.
The negative properties matter as much as the positive ones: non-http schemes,
fragment-only links, off-domain links, and plain non-keyword links must all
still be dropped.
"""

from __future__ import annotations

from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector
from tests.integration.fixtures.connectors.bulletin_pages import (
    EMPTY_PAGE_HTML,
    JS_RENDERED_BULLETIN_HTML,
    MEXT_STYLE_LIST_HTML,
    MOFA_KR_BULLETIN_BASE_URL,
    MOFA_KR_BULLETIN_LINKS_DEFAULT_KEYWORDS,
    MOFA_KR_BULLETIN_LINKS_WITH_BULLETIN_KEYWORDS,
    MOFA_KR_BULLETIN_PAGE_HTML,
)

BULLETIN_KEYWORDS = [
    "scholarship",
    "fellowship",
    "grant",
    "view.do",
    "seq",
    "m_11417",
    "report",
    "notice",
    "detail",
]


def _connector(base_url: str, *, keywords: list[str] | None = None) -> GenericPlaywrightConnector:
    """A connector instance with a config and no browser, for extraction only."""
    config = ConnectorConfig(
        source_id=uuid_from_struct("00000000-0000-0000-0000-000000000001"),
        url=base_url,
        timeout=30,
        custom_settings=({"keywords": keywords} if keywords is not None else {}),
    )
    connector = GenericPlaywrightConnector.__new__(GenericPlaywrightConnector)
    connector.config = config
    return connector


def uuid_from_struct(raw: str):
    from uuid import UUID

    return UUID(raw)


class TestDiscoveryExtraction:
    """What the connector finds on a page, and on what evidence."""

    def test_anchor_text_discovers_opaque_board_entries(self):
        """The corrected behaviour, and the point of the whole change.

        Both discoverable entries have URLs that say nothing about funding. They
        are found because their anchor text does. Before anchor text was read,
        this list was empty and the source yielded nothing.
        """
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL)
        discovered = connector._extract_candidate_links(
            MOFA_KR_BULLETIN_PAGE_HTML, MOFA_KR_BULLETIN_BASE_URL
        )
        assert discovered == MOFA_KR_BULLETIN_LINKS_DEFAULT_KEYWORDS

    def test_anchor_text_is_carried_alongside_each_url(self):
        """Discovery returns the evidence, not just the address.

        Ranking cannot use a label it was never given, which is why the pair
        form exists.
        """
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL)
        pairs = connector._extract_candidate_links_with_context(
            MOFA_KR_BULLETIN_PAGE_HTML, MOFA_KR_BULLETIN_BASE_URL
        )
        anchors = dict(pairs)
        assert anchors[
            "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759977"
        ].startswith("2025-2026 Scholarship")
        assert "Scholarship" in anchors[
            "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759978"
        ]

    def test_bulletin_keywords_discover_every_board_entry(self):
        """A keyword set that names the board reaches the board's whole listing."""
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL, keywords=BULLETIN_KEYWORDS)
        discovered = connector._extract_candidate_links(
            MOFA_KR_BULLETIN_PAGE_HTML, MOFA_KR_BULLETIN_BASE_URL
        )
        assert discovered == MOFA_KR_BULLETIN_LINKS_WITH_BULLETIN_KEYWORDS

    def test_non_http_schemes_and_fragment_links_are_never_discovered(self):
        """Script links, anchors and mail links are not destinations."""
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL, keywords=BULLETIN_KEYWORDS)
        discovered = connector._extract_candidate_links(
            MOFA_KR_BULLETIN_PAGE_HTML, MOFA_KR_BULLETIN_BASE_URL
        )
        assert not any("javascript:" in url for url in discovered)
        assert not any("mailto:" in url for url in discovered)
        assert not any(url.endswith("#top") for url in discovered)

    def test_empty_page_produces_no_candidates(self):
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL)
        assert (
            connector._extract_candidate_links(EMPTY_PAGE_HTML, MOFA_KR_BULLETIN_BASE_URL)
            == []
        )

    def test_script_embedded_markup_is_not_a_dom_anchor(self):
        """Only rendered anchors count.

        The fixture keeps its links inside a script, which is the pre-render
        snapshot. Extraction reads the DOM, so it finds nothing there; the live
        path evaluates the script in the browser first and reads the result.
        """
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL)
        assert (
            connector._extract_candidate_links(
                JS_RENDERED_BULLETIN_HTML, MOFA_KR_BULLETIN_BASE_URL
            )
            == []
        )

    def test_relative_urls_are_resolved_against_the_base_url(self):
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL)
        discovered = connector._extract_candidate_links(
            MOFA_KR_BULLETIN_PAGE_HTML, MOFA_KR_BULLETIN_BASE_URL
        )
        assert discovered
        assert all(url.startswith("https://www.mofa.go.kr/il-en/brd/m_11417/") for url in discovered)

    def test_fragment_and_duplicate_urls_collapse_to_one_candidate(self):
        html = """
        <html><body>
          <a href="view.do?seq=759978">Scholarship</a>
          <a href="view.do?seq=759978#frag">Scholarship</a>
          <a href="view.do?seq=759978">Scholarship</a>
        </body></html>
        """
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL)
        discovered = connector._extract_candidate_links(html, MOFA_KR_BULLETIN_BASE_URL)
        assert len(discovered) == 1
        assert discovered[0].endswith("view.do?seq=759978")

    def test_external_links_are_not_discovered(self):
        html = """
        <html><body>
          <a href="https://external.example.org/scholarship">Scholarship abroad</a>
          <a href="view.do?seq=759978">Scholarship</a>
        </body></html>
        """
        connector = _connector(MOFA_KR_BULLETIN_BASE_URL)
        discovered = connector._extract_candidate_links(html, MOFA_KR_BULLETIN_BASE_URL)
        assert not any("external.example.org" in url for url in discovered)
        assert any("seq=759978" in url for url in discovered)

    def test_a_listing_keeps_its_own_named_programme_links(self):
        """A MEXT-shaped list resolves relative links and drops the rest."""
        base = "https://www.mext.go.jp/en/program/2025/detail.html"
        connector = _connector(base)
        discovered = connector._extract_candidate_links(MEXT_STYLE_LIST_HTML, base)
        assert any("detail/2026" in url for url in discovered)
        assert not any("contact" in url for url in discovered)
        assert not any("external.example.org" in url for url in discovered)
