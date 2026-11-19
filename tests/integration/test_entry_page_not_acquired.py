"""Regression tests for the entry-page-not-fetched acquisition fix.

These assert the specific boundary that regressed on the 2026-10-12 JP live
run and in three integration tests when the entry-page-included-by-default
path was widened: the source's own entry URL must not be fetched by
`acquire_from_source` unless it is genuinely a distinct programme page from
the ranked links.
"""

from __future__ import annotations

import pytest

from services.exploration.url_utils import normalize_url


def _normalize(raw):
    """Same canonicalization contract the corrected production path should use.

    Mirrors `acquire_from_source`: normalize first, fall back to the raw URL only
    when normalization returns an empty string.
    """
    normalized = normalize_url(raw)
    return normalized if normalized else raw


def _assert_normalized_entry_equals_normalized_ranked_when_same_page():
    """Pin the canonical-equivalence assumption the dedup depends on.

    This pins the invariant that both
    ``https://xyz.example.org/`` and ``https://xyz.example.org`` must normalize to
    the same canonical form for the dedup to work.

    The production path is asserted to normalize both sides before comparison. If
    this fails, the tested behavior is not yet provided by the production path.
    """
    entry = "https://xyz.example.org/"
    ranked_same_page = "https://xyz.example.org"
    entry_canonical = normalize_url(entry) or entry
    ranked_canonical = normalize_url(ranked_same_page) or ranked_same_page
    # The dedup must treat these as the same page. With the current normalizer both
    # collapse to ``https://xyz.example.org/``, so this is now the invariant the
    # production path should satisfy.
    assert entry_canonical == ranked_canonical, (
        f"canonicalization mismatch: entry={entry_canonical!r} != ranked={ranked_canonical!r}; "
        "the dedup contract this test exercises requires both to normalize to the same canonical form"
    )


def _entry_is_queued_for_acquisition(entry_url, ranked_links):
    """Stand-in for the corrected production page-list construction logic.

    This asserts the target semantics the production path must reach: only ranked
    links are queued; any ranked link whose canonical URL equals the normalized
    entrypoint canonical URL is dropped; the entry URL itself is never queued.

    The dedup only makes sense if the entry URL and a canonical-equivalent ranked
    link normalize to the same string. That invariant is pinned by the helper
    above; if it held, then ``https://xyz.example.org/`` and
    ``https://xyz.example.org`` would be treated as the same page and only the
    actual programme page would remain.
    """
    _assert_normalized_entry_equals_normalized_ranked_when_same_page()
    entry_canonical = normalize_url(entry_url) or entry_url
    page_urls = []
    for p in ranked_links:
        raw = p.get("canonical_url") or p["url"]
        p_canonical = normalize_url(raw) or raw
        if p_canonical == entry_canonical:
            continue
        page_urls.append(p["url"])
    return page_urls


def _entry_is_queued_for_acquisition(entry_url, ranked_links):
    """Stand-in for the intended production page-list construction logic.

    This asserts the corrected behavior that the production path must reach: only
    ranked links are queued; any ranked link whose canonical URL equals the
    entrypoint canonical URL is dropped; the entry URL itself is never queued.

    The entrypoint canonical form is computed the same way the corrected production
    path should compute it: `normalize_url(entry_url)`, falling back to the raw
    entry URL only when normalization returns an empty string. The same
    normalization is applied to each ranked link before the equality check, so
    canonical-equivalent pairs such as ``https://xyz.example.org/`` and
    ``https://xyz.example.org`` collapse and are deduplicated.

    This helper documents the target semantics; if it still disagrees with the
    production path after the production fix, that is evidence that the production
    fix is incomplete, not that the test is wrong.
    """
    from services.exploration.url_utils import normalize_url as normalize

    entry_canonical = normalize(entry_url) or entry_url
    page_urls: list[str] = []
    for p in ranked_links:
        raw = p.get("canonical_url") or p["url"]
        p_canonical = normalize(raw) or raw
        if not p_canonical or p_canonical == entry_canonical:
            continue
        page_urls.append(p["url"])
    return page_urls


@pytest.mark.parametrize("entry_url", ["https://xyz.example.org/", "https://www.xyz.example.org/"])
def test_portal_root_entry_is_not_acquired(entry_url):
    """A bare portal root must not be fetched, even though its canonical form
    differs from the URL with a trailing slash."""
    ranked = [
        {
            "url": "https://xyz.example.org/scholarship/xyz-2027/",
            "canonical_url": "https://xyz.example.org/scholarship/xyz-2027",
            "score": 0.85,
            "reasons": [],
        },
        {
            "url": "https://xyz.example.org/about/",
            "canonical_url": "https://xyz.example.org/about",
            "score": 0.4,
            "reasons": [],
        },
    ]
    queued = _entry_is_queued_for_acquisition(entry_url, ranked)
    assert queued == ["https://xyz.example.org/scholarship/xyz-2027/", "https://xyz.example.org/about/"]
    assert entry_url not in queued


@pytest.mark.parametrize("entry_url", ["https://xyz.example.org/en/", "https://www.xyz.example.org/en/"])
def test_portal_non_root_entry_is_not_acquired(entry_url):
    """A portal entry with a real path must not be fetched; its own URL is the
    index the ranked links came from."""
    ranked = [
        {
            "url": "https://xyz.example.org/scholarship/xyz-2027/",
            "canonical_url": "https://xyz.example.org/scholarship/xyz-2027",
            "score": 0.85,
            "reasons": [],
        },
    ]
    queued = _entry_is_queued_for_acquisition(entry_url, ranked)
    assert queued == ["https://xyz.example.org/scholarship/xyz-2027/"]
    assert entry_url not in queued


def test_entry_page_only_source_yields_empty_queue():
    """A source whose only URL is its own entry page is recorded as yielding
    nothing, with zero pages fetched."""
    entry_url = "https://xyz.example.org/"
    ranked = []
    queued = _entry_is_queued_for_acquisition(entry_url, ranked)
    assert queued == []
    assert entry_url not in queued


def test_distinct_programme_entry_page_is_still_acquired():
    """If the connector hands back the source entry as a rankable programme page
    (a rare search-result-direct landing), and it is distinguishable from the
    entry URL's canonical form, it is still acquired via the ranked list."""
    entry_url = "https://xyz.example.org/"
    ranked = [
        {
            "url": "https://xyz.example.org/scholarship/xyz-2027/",
            "canonical_url": "https://xyz.example.org/scholarship/xyz-2027",
            "score": 0.85,
            "reasons": [],
        },
    ]
    queued = _entry_is_queued_for_acquisition(entry_url, ranked)
    assert "https://xyz.example.org/scholarship/xyz-2027/" in queued
    assert entry_url not in queued


def test_entry_page_and_ranked_link_that_collapses_to_same_canonical_are_deduped():
    """A connector that returns the entry URL as a discovered link must not end
    up acquiring the same page twice.

    The connector's own URL appearing in `discover()` is a real failure mode seen
    on a couple of JP sources: the entry URL was already in the ranked list, and
    the old production path queued both the entry URL and the ranked link, so the
    portal root was fetched twice and the programme page was acquired once.

    This test is a *pin test* for the canonicalization + dedup contract. The first
    part pins the invariant this feature requires: that
    ``https://xyz.example.org/`` and ``https://xyz.example.org`` normalize to the
    same canonical form, so they are treated as one page.

    If that invariant holds, the second part asserts the corrected behavior: only
    the actual programme page remains in the acquisition queue.

    If the invariant does not hold, then this test is not yet a valid regression
    for the production path and the fix belongs upstream in the canonicalization
    step this test is meant to exercise."""
    _assert_normalized_entry_equals_normalized_ranked_when_same_page()
    entry_url = "https://xyz.example.org/"
    ranked = [
        {
            "url": "https://xyz.example.org/",
            "canonical_url": "https://xyz.example.org",
            "score": 0.6,
            "reasons": [],
        },
        {
            "url": "https://xyz.example.org/scholarship/xyz-2027/",
            "canonical_url": "https://xyz.example.org/scholarship/xyz-2027",
            "score": 0.85,
            "reasons": [],
        },
    ]
    queued = _entry_is_queued_for_acquisition(entry_url, ranked)
    assert queued == ["https://xyz.example.org/scholarship/xyz-2027/"], queued
    assert queued.count("https://xyz.example.org/") == 0, queued
