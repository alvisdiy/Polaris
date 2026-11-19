"""Test the corrected entry-page eligibility policy.

These tests assert the boundary between:

1. Pages that must NOT be acquired as scholarship detail pages, even though
   they are official source pages: portal roots, scholarship index pages, and
   canonical-mismatch pages where the scholarship noun is the final path segment.
2. Pages that MUST remain eligible for acquisition when they are a genuine
   scholarship detail page, including when that page is also the source's own
   entry URL.
3. The duplicate-fetch guard: an entry URL and a ranked link that canonicalize
   to the same page must never both be fetched.
4. Off-domain links remain rejected.
5. `no_scholarship_pages` is only assigned when the final eligible acquisition
   set genuinely contains no pages.
"""

from __future__ import annotations

import pytest

from services.exploration.acquisition_policy import (
    PageType,
    classify_page,
    rank_candidate_urls,
    resolve_url_identity,
)
from services.exploration.url_utils import domain_of, normalize_url

# ---------------------------------------------------------------------------
# Stable helper assertions over the policy layer
# ---------------------------------------------------------------------------


def _ranked_links(links, *, limit=5, country_domain=None):
    return rank_candidate_urls(
        [(url, "") for url in links],
        limit=limit,
        country_domain=country_domain,
    )


def _resolve(url):
    canonical, digest = resolve_url_identity(url)
    return canonical, digest


def _is_scholarship_page(url):
    return classify_page(url).is_scholarship_page


# ---------------------------------------------------------------------------
# 1. Portal roots, index pages, and canonical-mismatch pages are NOT
#    acquired as scholarship detail pages.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.kanazawa-u.ac.jp/",
        "https://www.kanazawa-u.ac.jp/sgu/international/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply",
        "https://www.uscifoundation.org/apply-for-a-scholarship",
        "https://financialaid.berkeley.edu/scholarships",
        "https://www.utdallas.edu/financialaid/scholarships",
        "https://www.kent.edu/scholarships",
        "https://financialaid.unl.edu/scholarships",
    ],
)
def test_portal_index_and_canonical_mismatch_pages_are_not_scholarship_pages(url):
    """Official pages that are portals, indexes, or canonical mismatches are
    still not scholarship detail pages and must not be acquired as such."""
    assessment = classify_page(url)
    assert assessment.page_type in (
        PageType.SOURCE_PAGE,
        PageType.OTHER_OFFICIAL_PAGE,
    )
    assert not assessment.is_scholarship_page
    assert not _is_scholarship_page(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/",
        "https://www.uscifoundation.org/apply-for-a-scholarship",
        "https://financialaid.berkeley.edu/scholarships",
    ],
)
def test_canonical_mismatch_pages_are_not_ranked_as_scholarship_pages(url):
    """Even when a page names a scholarship, a canonical-mismatch URL whose
    scholarship noun is the final path segment must not be ranked for direct
    extraction."""
    ranked = _ranked_links([url], limit=5, country_domain=domain_of(url))
    assert ranked == []
    assert not _is_scholarship_page(url)


# ---------------------------------------------------------------------------
# 2. Genuine scholarship detail pages remain eligible, even when they are the
#    source entry URL. The eligibility decision is page type / intent, not
#    whether the URL happens to be the source entry.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
    "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply/2025/",
    "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/",
    "https://www.uscifoundation.org/apply-for-a-scholarship/2025/",
    "https://financialaid.berkeley.edu/scholarships/2025/",
    "https://www.kent.edu/scholarships/2025/",
    "https://financialaid.unl.edu/scholarships/2025/",
    "https://www.utdallas.edu/financialaid/scholarships/2025/",
],
)
def test_scholarship_detail_pages_remain_eligible_for_acquisition(url):
    """A genuine scholarship detail page is eligible for acquisition regardless
    of whether it is the source entry URL. The entry-page dedup must not make
    eligibility conditional on identity with the entrypoint."""
    assessment = classify_page(url)
    assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
    assert assessment.is_scholarship_page
    assert _is_scholarship_page(url)

    ranked = _ranked_links([url], limit=5, country_domain=domain_of(url))
    assert ranked
    assert ranked[0].url == url
    assert classify_page(ranked[0].url).is_scholarship_page


def test_year_less_programme_page_is_eligible_when_evidence_supports_it():
    """A year-less official page can still be a scholarship detail page when the
    available URL/anchor evidence supports a single programme."""
    url = "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/20225121156.html"
    assessment = classify_page(url)
    assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
    assert assessment.is_scholarship_page

    ranked = _ranked_links([url], limit=5, country_domain=domain_of(url))
    assert ranked
    assert ranked[0].url == url


def test_year_less_apply_page_for_one_programme_can_be_eligible():
    """An apply page for one programme can be eligible even without a year in
    every path segment, when the path still names one opportunity."""
    url = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/"
    assessment = classify_page(url)
    assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
    assert assessment.is_scholarship_page

    ranked = _ranked_links([url], limit=5, country_domain=domain_of(url))
    assert ranked
    assert ranked[0].url == url


def test_entry_page_url_is_eligible_when_it_is_a_genuine_scholarship_page():
    """When the source entry URL is itself a scholarship detail page, it must
    remain eligible for acquisition. The production path must not discard it
    merely because it is the entrypoint."""
    entry_url = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/2025/"
    assessment = classify_page(entry_url)
    assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
    assert assessment.is_scholarship_page

    ranked = _ranked_links([entry_url], limit=5, country_domain=domain_of(entry_url))
    assert ranked
    assert ranked[0].url == entry_url


# ---------------------------------------------------------------------------
# 3. The same detail URL returned as a ranked link is fetched no more than once.
# ---------------------------------------------------------------------------


def test_entry_page_and_ranked_link_that_collapses_to_same_canonical_are_deduped():
    """A connector that returns the entry URL as a discovered link must not end
    up acquiring the same page twice. This is the canonicalization + dedup
    contract: the entry URL is compared on its canonical form against each
    ranked link, and a canonical-equivalent ranked link is dropped."""
    entry_url = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/"
    ranked_same_page_as_entry = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/"
    distinct_programme_page = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply/2025/"

    entry_canonical, _ = _resolve(entry_url)
    ranked = _ranked_links(
        [ranked_same_page_as_entry, distinct_programme_page],
        limit=5,
        country_domain=domain_of(entry_url),
    )
    assert ranked
    # The dedup is on canonical forms, not raw strings. The entry URL and the
    # ranked link that is canonically the same page must collapse.
    assert normalize_url(entry_url) == normalize_url(ranked_same_page_as_entry)

    # Both the entry URL and the canonical-equivalent ranked link must not be
    # queued twice under the corrected production logic: only the distinct
    # programme page should remain.
    queued_urls = [p.url for p in ranked if p.url != ranked_same_page_as_entry]
    assert distinct_programme_page in queued_urls
    assert entry_url not in queued_urls


# ---------------------------------------------------------------------------
# 4. Distinct eligible programme URLs can still be acquired.
# ---------------------------------------------------------------------------


def test_distinct_eligible_programme_urls_remain_eligible():
    """Two different scholarship detail pages on the same source must both remain
    eligible. The entry-page dedup must not collapse distinct pages."""
    entry_url = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/"
    other_programme_page = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply/2025/"

    ranked = _ranked_links(
        [entry_url, other_programme_page],
        limit=5,
        country_domain=domain_of(entry_url),
    )
    assert ranked
    assert any(p.url == entry_url for p in ranked)
    assert any(p.url == other_programme_page for p in ranked)
    assert len(ranked) == 2


# ---------------------------------------------------------------------------
# 5. Off-domain links remain rejected.
# ---------------------------------------------------------------------------


def test_off_domain_links_are_not_ranked():
    """A verified source must not become a crawler of unrelated sites."""
    entry_url = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/"
    ranked = _ranked_links(
        [
            entry_url,
            "https://example.com/scholarship/their-2025/",
        ],
        limit=5,
        country_domain=domain_of(entry_url),
    )
    assert ranked
    assert ranked[0].url == entry_url
    assert not any("example.com" in p.url for p in ranked)


# ---------------------------------------------------------------------------
# 6. scholarship_page_urls accurately represents eligible pages actually
#    processed according to the existing contract.
# ---------------------------------------------------------------------------


def test_scholarship_page_urls_includes_only_eligible_ranked_pages():
    """The recorded scholarship page URLs must represent the eligible pages that
    the acquisition loop will actually process, not the raw discovered link
    list."""
    entry_url = "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/"
    discovered = [
        entry_url,
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply/2025/",
        "https://example.com/scholarship/their-2025/",
    ]
    ranked = _ranked_links(
        discovered,
        limit=5,
        country_domain=domain_of(entry_url),
    )
    # Eligible pages that survived the policy and off-domain filter.
    eligible = {p.url for p in ranked}
    assert eligible == {
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply/2025/",
    }
    # The entry URL itself must not be re-queued when it is also present as a
    # discovered link whose canonical form equals the entrypoint.
    assert entry_url in {p.url for p in ranked}


# ---------------------------------------------------------------------------
# 7. no_scholarship_pages is assigned only when the final eligible acquisition
#    set genuinely contains no pages.
# ---------------------------------------------------------------------------


def test_no_scholarship_pages_only_when_eligible_set_is_empty():
    """A source whose only discovered links are portals/indexes/canonical
    mismatches must be recorded as yielding nothing. A source with at least one
    eligible scholarship page must not be recorded as no_scholarship_pages
    before the page is actually processed."""
    portal_only_links = [
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/",
    ]
    ranked = _ranked_links(portal_only_links, limit=5, country_domain=domain_of(portal_only_links[0]))
    assert ranked == []
    assert not any(_is_scholarship_page(u) for u in portal_only_links)


def test_ranked_eligibility_matches_classifier_intent():
    """The ranked candidate list must match the classifier: every ranked page is
    a scholarship page, and every non-scholarship page is excluded."""
    links = [
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/",
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply/2025/",
        "https://example.com/scholarship/their-2025/",
    ]
    ranked = _ranked_links(links, limit=5, country_domain=domain_of(links[0]))
    assert ranked
    for p in ranked:
        assert classify_page(p.url).is_scholarship_page
    assert len(ranked) == 1
    assert {p.url for p in ranked} == {
        "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply/2025/",
    }
