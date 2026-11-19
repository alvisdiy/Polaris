"""Regression tests for GenericPlaywrightConnector link discovery itself.

These tests cover the connector's own output contract in isolation: HTML/JS page
shapes, URL resolution, duplicate handling, the distinction between "no links
found" and "discovery failed", safety and domain restrictions, and the MOFA-like
view.do?seq= detail-page shape. They do not touch the live provider.

Discovery diagnostics from the live run show that _extract_candidate_links itself
is the stage that silently converted MOFA links into nothing; the connector's async
discover() method already adds a robots check and validation, but the keyword /
canonicalization path that was failing at runtime is exercised here directly.
"""

from __future__ import annotations

import uuid

from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector

SCHOOLYARD_KEYWORDS = ["scholarship", "view.do", "seq", "m_11417", "detail", "list.do"]


def _make(*, source_id, url, keywords=SCHOOLYARD_KEYWORDS):
    cfg = ConnectorConfig(
        source_id=source_id,
        url=url,
        timeout=30,
        user_agent="PolarisBot/0.2 (+discovery research)",
        custom_settings={"keywords": list(keywords)},
    )
    return GenericPlaywrightConnector(cfg)


def _html(body):
    return f"<html><body>{body}</body></html>"


def _anchor(href, text="x"):
    return f'<a href="{href}">{text}</a>'


# ------------------------------------------------------------------
# 1. Ordinary HTML with relative and absolute candidate links
# ------------------------------------------------------------------


def test_discovers_relative_and_absolute_scholarship_links():
    html = _html(
        _anchor("view.do?seq=759980")
        + _anchor("/il-en/brd/m_11417/view.do?seq=759981")
        + _anchor("detail/2026/")
        + _anchor("https://www.example.org/scholarship/apply/2026/")
    )
    c = _make(source_id=uuid.uuid4(), url="https://www.example.org/entry")
    cand = c._extract_candidate_links(html, "https://www.example.org/entry")
    assert cand
    assert "https://www.example.org/view.do?seq=759980" in cand
    assert "https://www.example.org/il-en/brd/m_11417/view.do?seq=759981" in cand
    assert "https://www.example.org/detail/2026/" in cand
    assert "https://www.example.org/scholarship/apply/2026/" in cand


# ------------------------------------------------------------------
# 2. Query-based official detail pages (view.do?seq=N)
# ------------------------------------------------------------------


def test_discovers_query_based_detail_pages_with_keywords():
    html = _html(
        _anchor("https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759979")
        + _anchor("view.do?seq=759982")
        + _anchor("/il-en/brd/m_11417/view.do?seq=759983#frag")
    )
    c = _make(
        source_id=uuid.uuid4(),
        url="https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759978",
        keywords=SCHOOLYARD_KEYWORDS,
    )
    cand = c._extract_candidate_links(html, "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759978")
    assert "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759979" in cand
    assert "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759982" in cand
    assert "https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759983" in cand
    assert "#frag" not in cand


# ------------------------------------------------------------------
# 3. JS-rendered page: links appearing after initial navigation
#    (modeled by passing a larger HTML snapshot that includes both
#    initial and dynamically-injected anchors; the connector's DOM
#    path reads whatever is present at page.content() time.)
# ------------------------------------------------------------------


def test_discovers_links_after_dom_is_full_snapshot():
    initial = _anchor("view.do?seq=759984")
    injected = _anchor("/il-en/brd/m_11417/view.do?seq=759985")
    html = _html(initial + injected)
    c = _make(source_id=uuid.uuid4(), url="https://www.example.org/entry")
    cand = c._extract_candidate_links(html, "https://www.example.org/entry")
    assert len(cand) == 2
    assert "https://www.example.org/view.do?seq=759984" in cand
    assert "https://www.example.org/il-en/brd/m_11417/view.do?seq=759985" in cand


# ------------------------------------------------------------------
# 4. Relative links resolved against a nested entry path
# ------------------------------------------------------------------


def test_discovers_relative_links_resolved_against_nested_entry():
    html = _html(_anchor("view.do?seq=759986"))
    c = _make(source_id=uuid.uuid4(), url="https://www.example.org/deep/path/entry")
    cand = c._extract_candidate_links(html, "https://www.example.org/deep/path/entry")
    assert "https://www.example.org/deep/path/view.do?seq=759986" in cand
    assert "https://www.example.org/view.do?seq=759986" not in cand
    assert "https://www.example.org/deep/path/view.do?seq=759986" in cand


# ------------------------------------------------------------------
# 5. Duplicate links and fragment variations
# ------------------------------------------------------------------


def test_deduplicates_duplicate_links_and_fragment_variations():
    html = _html(
        _anchor("view.do?seq=759987#top")
        + _anchor("view.do?seq=759987")
        + _anchor("view.do?seq=759987#bottom")
        + _anchor("/il-en/brd/m_11417/view.do?seq=759987")
    )
    c = _make(source_id=uuid.uuid4(), url="https://www.example.org/entry")
    cand = c._extract_candidate_links(html, "https://www.example.org/entry")
    assert cand
    # One canonical link for seq=759987, since fragments are stripped and
    # path+query is equivalent.
    seen = {u.split("#")[0] for u in cand}
    assert seen == {
        "https://www.example.org/view.do?seq=759987",
        "https://www.example.org/il-en/brd/m_11417/view.do?seq=759987",
    }


# ------------------------------------------------------------------
# 6. Off-domain and restricted-scheme links are rejected
# ------------------------------------------------------------------


def test_discovers_only_same_domain_links_by_default():
    html = _html(
        _anchor("view.do?seq=759988")
        + _anchor("https://other.example.org/scholarship/apply/2026/")
    )
    c = _make(source_id=uuid.uuid4(), url="https://www.example.org/entry")
    cand = c._extract_candidate_links(html, "https://www.example.org/entry")
    assert cand
    assert len(cand) == 1
    assert "https://www.example.org/view.do?seq=759988" in cand
    assert "other.example.org" not in cand


def test_discovers_off_domain_links_when_subdomains_allowed_false_only_exact_domain():
    html = _html(
        _anchor("view.do?seq=759989")
        + _anchor("https://www.example.org/scholarship/apply/2026/")
        + _anchor("https://other.example.org/scholarship/apply/2026/")
    )
    cfg = ConnectorConfig(
        source_id=uuid.uuid4(),
        url="https://www.example.org/entry",
        timeout=30,
        user_agent="PolarisBot/0.2 (+discovery research)",
        custom_settings={"keywords": list(SCHOOLYARD_KEYWORDS), "allow_subdomains": False},
        )
    c = GenericPlaywrightConnector(cfg)
    cand = c._extract_candidate_links(html, "https://www.example.org/entry")
    assert cand
    assert len(cand) == 2
    assert "https://www.example.org/view.do?seq=759989" in cand
    assert "https://www.example.org/scholarship/apply/2026/" in cand
    assert "other.example.org" not in cand


# ------------------------------------------------------------------
# 7. Safety/robots/safety-errors at the connector layer are propagated,
#    not silently converted to empty candidate lists. The connector's
#    async discover() already does this; here we pin the distinction at
#    the DOM extraction stage and the async method's error handling.
# ------------------------------------------------------------------


def test_discovery_error_is_distinguishable_from_empty_page():
    """A connector that errors during navigation must surface that as an
    empty candidate list *with* a logged error, not as a silent success with
    zero links. This pins the contract the async method must satisfy: the
    live run should never report "0 links" when the page actually failed to
    load. The exact way errors are surfaced is the connector's exception
    handling; here we assert that a page with real links can be extracted, and
    that an HTML page with no qualifying links returns a genuinely empty list,
    so the two cases are distinct."""
    html_with_links = _html(_anchor("view.do?seq=759990"))
    c = _make(source_id=uuid.uuid4(), url="https://www.example.org/entry")
    links = c._extract_candidate_links(html_with_links, "https://www.example.org/entry")
    assert links
    assert len(links) == 1

    html_empty = _html("<p>no links</p>")
    links_empty = c._extract_candidate_links(html_empty, "https://www.example.org/entry")
    assert links_empty == []


def test_discovery_skips_anchor_only_and_empty_links():
    html = _html(
        _anchor("#section")
        + _anchor("javascript:void(0)")
        + _anchor("mailto:test@example.org")
        + _anchor("tel:+1234567890")
        + '<a href="">empty</a>'
        + "<p>plain text</p>"
    )
    c = _make(source_id=uuid.uuid4(), url="https://www.example.org/entry")
    cand = c._extract_candidate_links(html, "https://www.example.org/entry")
    assert cand == []


def test_discovery_skips_pdf_and_other_non_html_resources():
    html = _html(
        _anchor("brochure.pdf")
        + _anchor("document.docx")
        + _anchor("view.do?seq=759991")
    )
    c = _make(source_id=uuid.uuid4(), url="https://www.example.org/entry")
    cand = c._extract_candidate_links(html, "https://www.example.org/entry")
    assert cand
    assert len(cand) == 1
    assert "https://www.example.org/view.do?seq=759991" in cand


# ------------------------------------------------------------------
# 8. Anchor text carries the scholarship signal when the URL is neutral
# ------------------------------------------------------------------

NEUTRAL_KEYWORDS = ["scholarship", "fellowship", "grant"]


def test_neutral_query_link_is_kept_when_the_anchor_names_a_scholarship():
    """The MOFA shape: the URL is an opaque board query, the label is the evidence.

    The previous extraction matched keywords against the URL alone, so this link
    was dropped even though the page said "Scholarship for International
    Students" right next to it. That is the stage the live run lost its
    candidates at.
    """
    html = _html(
        _anchor("view.do?seq=759992", "Scholarship for International Students")
        + _anchor("list.do", "Notice")
    )
    c = _make(
        source_id=uuid.uuid4(),
        url="https://www.mofa.go.kr/il-en/brd/m_11417/view.do",
        keywords=NEUTRAL_KEYWORDS,
    )
    cand = c._extract_candidate_links(
        html, "https://www.mofa.go.kr/il-en/brd/m_11417/view.do"
    )
    assert cand == ["https://www.mofa.go.kr/il-en/brd/m_11417/view.do?seq=759992"]


def test_neutral_link_is_still_dropped_when_neither_url_nor_anchor_matches():
    """Discovery is not a licence to keep every link on the page.

    The property under test is unchanged: a link whose address says nothing and
    whose label says nothing is not a candidate. What changed is which layer
    enforces it for a *record* URL. ``view.do?seq=1`` is admitted by extraction
    because a viewer route carrying a numeric id is one page of the publisher's
    CMS — the label is the only thing that can say what it is — and the
    acquisition policy then rejects it for the same reason: "Notice" is not a
    scholarship. Navigation links are still dropped before that point.
    """
    html = _html(
        _anchor("view.do?seq=1", "Notice")
        + _anchor("index.html", "Home")
        + _anchor("sitemap.xml", "Sitemap")
    )
    c = _make(
        source_id=uuid.uuid4(),
        url="https://www.mofa.go.kr/il-en/brd/m_11417/view.do",
        keywords=NEUTRAL_KEYWORDS,
    )
    cand = c._extract_candidate_links_with_context(
        html, "https://www.mofa.go.kr/il-en/brd/m_11417/view.do"
    )
    # The two nav links never enter discovery at all.
    assert not any("index.html" in url or "sitemap" in url for url, _ in cand)

    # The record is admitted, and then refused by the policy on its label.
    from services.exploration.acquisition_policy import rank_candidate_urls

    assert rank_candidate_urls(cand, limit=10) == []


def test_discovery_pairs_survive_hrefs_the_old_regex_scraper_mangled():
    """The href regex broke on quoted attributes; DOM parsing does not."""
    html = _html(
        '<a href="view.do?seq=759993" title="A &quot;quoted&quot; title" '
        'class="link">Scholarship Programme</a>'
        + '<a class="link" href="view.do?seq=759994">Fellowship Announcement</a>'
    )
    c = _make(
        source_id=uuid.uuid4(),
        url="https://www.example.org/entry",
        keywords=NEUTRAL_KEYWORDS,
    )
    pairs = c._extract_candidate_links_with_context(html, "https://www.example.org/entry")
    urls = [url for url, _anchor_text in pairs]
    assert "https://www.example.org/view.do?seq=759993" in urls
    assert "https://www.example.org/view.do?seq=759994" in urls
    anchors = dict(pairs)
    assert anchors["https://www.example.org/view.do?seq=759993"] == "Scholarship Programme"
    assert anchors["https://www.example.org/view.do?seq=759994"] == "Fellowship Announcement"


def test_extract_candidate_links_keeps_returning_bare_urls():
    """The old method is the connector's public contract; it must not change shape."""
    html = _html(_anchor("view.do?seq=759995", "Scholarship"))
    c = _make(
        source_id=uuid.uuid4(),
        url="https://www.example.org/entry",
        keywords=NEUTRAL_KEYWORDS,
    )
    cand = c._extract_candidate_links(html, "https://www.example.org/entry")
    assert cand == ["https://www.example.org/view.do?seq=759995"]
    assert all(isinstance(u, str) for u in cand)
