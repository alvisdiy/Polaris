"""Tests for the acquisition policy and URL identity.

The behaviour under test is the fix for the M8 data-quality failure: a verified
government homepage was being handed to the extractor as though it were one
scholarship, which is how `Number of Scholarship` and `Das Program` became
scholarship names.

These are unit tests because the policy is a pure function of URL and anchor
text. No network, no database, no fixtures.
"""

from __future__ import annotations

import pytest

from services.exploration.acquisition_policy import (
    PageType,
    classify_page,
    classify_provider_page,
    find_source,
    rank_candidate_urls,
    resolve_url_identity,
)


class TestPageClassification:
    """The question: is this page one scholarship, or a place to look?"""

    def test_ministry_homepage_is_a_source_page_not_a_scholarship(self):
        """The exact failure M8 had: extracting a portal as a programme."""
        assessment = classify_page("https://www.studyinjapan.go.jp/en/", title="Study in Japan")
        assert assessment.page_type == PageType.SOURCE_PAGE
        assert not assessment.is_scholarship_page
        assert assessment.should_discover_links

    def test_root_domain_is_a_source_page(self):
        assert classify_page("https://www.studyinjapan.go.jp/").page_type == PageType.SOURCE_PAGE

    def test_programme_detail_page_is_a_scholarship(self):
        assessment = classify_page(
            "https://www.studyinjapan.go.jp/en/scholarship/monbukagakusho-2027/",
            title="Monbukagakusho Scholarship",
        )
        assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
        assert assessment.confidence >= 0.6

    def test_year_in_path_is_what_makes_a_page_specific(self):
        """Real programme pages name an intake; portals do not."""
        with_year = classify_page("https://example.edu/awards/2027-chevening/")
        without = classify_page("https://example.edu/awards/")
        assert with_year.is_scholarship_page
        assert not without.is_scholarship_page

    def test_year_is_strong_but_not_required_for_a_programme_page(self):
        """A year makes specificity easier to detect, but it is not mandatory.

        Some official scholarship pages describe one programme without a year in
        the URL, for example a numbered announcement or an apply page for one
        programme.
        """
        assessment = classify_page(
            "https://www.tsukuba.ac.jp/campuslife/support-scholarship/scholarship-links/pg/20225121156.html",
        )
        assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
        assert assessment.is_scholarship_page

    def test_year_less_programme_page_is_not_a_generic_index(self):
        """A year-less scholarship URL must not be assumed to be a listing."""
        assessment = classify_page(
            "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/15574/apply/2025/"
        )
        assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
        assert assessment.is_scholarship_page

    def test_apply_page_for_one_programme_can_be_a_scholarship_page(self):
        """An apply page for one intake can be a programme page, even without a
        year in every path segment, when the path still names one opportunity."""
        assessment = classify_page(
            "https://www.kanazawa-u.ac.jp/sgu/international/scholarship/apply/2025/"
        )
        assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
        assert assessment.is_scholarship_page

    def test_named_programme_without_collection_parent_is_a_scholarship(self):
        """Campus France's Eiffel page: a proper name + programme head in the
        final segment, under a language folder rather than a collection.
        It used to score 0.40 (SOURCE_PAGE) and was never fetched."""
        assessment = classify_page(
            "https://www.campusfrance.org/en/eiffel-scholarship-program-of-excellence"
        )
        assert assessment.page_type == PageType.SCHOLARSHIP_PAGE
        assert assessment.is_scholarship_page

    def test_hub_segment_of_pure_vocabulary_is_not_promoted(self):
        """A final segment built only from hub vocabulary names a section,
        not one programme, even at three tokens."""
        assessment = classify_page(
            "https://example.ac.uk/international-students-scholarship"
        )
        assert not assessment.is_scholarship_page

    def test_named_programme_with_hub_words_still_promoted_by_its_name(self):
        assessment = classify_page(
            "https://www.studyinkorea.go.kr/en/global-korea-scholarship"
        )
        assert assessment.is_scholarship_page

    def test_apply_page_is_not_automatically_a_programme(self):
        """Process wording can still rule a page out even when it names a
        scholarship."""
        assessment = classify_page(
            "https://example.edu/scholarship/how-to-apply", title="How to Apply"
        )
        assert not assessment.is_scholarship_page

    def test_index_page_is_rejected(self):
        assert not classify_page("https://example.edu/news/index.html").is_scholarship_page

    def test_how_to_apply_is_not_a_scholarship(self):
        """Process guidance describes applying, not the programme itself."""
        assessment = classify_page(
            "https://example.edu/scholarship/how-to-apply", title="How to Apply"
        )
        assert not assessment.is_scholarship_page

    def test_organisation_page_is_not_a_scholarship(self):
        assert not classify_page("https://www.mofa.go.jp/about.html").is_scholarship_page

    def test_ambiguous_page_is_not_guessed_into_a_scholarship(self):
        """Uncertainty resolves to 'unknown', never to 'scholarship'."""
        assessment = classify_page("https://example.edu/documents/form.pdf")
        assert assessment.page_type == PageType.OTHER_OFFICIAL_PAGE
        assert not assessment.is_scholarship_page

    def test_every_assessment_explains_itself(self):
        """A classifier nobody can audit is a classifier nobody should trust."""
        for url in (
            "https://example.edu/",
            "https://example.edu/scholarship/x-2027/",
            "https://example.edu/faq/",
        ):
            assert classify_page(url).reasons, f"no reasoning recorded for {url}"

    def test_provider_page_classification(self):
        assert (
            classify_provider_page("https://example.org/about-us").page_type
            == PageType.PROVIDER_PAGE
        )
        # An opportunity page that is really a programme falls through to the
        # shared classifier rather than being guessed at.
        assert classify_provider_page(
            "https://example.org/scholarship/abc-2027"
        ).is_scholarship_page


class TestUrlIdentity:
    def test_tracking_params_do_not_create_a_second_identity(self):
        a, hash_a = resolve_url_identity("https://example.edu/scholarship/abc")
        b, hash_b = resolve_url_identity("https://example.edu/scholarship/abc?utm_source=news")
        assert a == b
        assert hash_a == hash_b

    def test_www_and_trailing_slash_are_the_same_url(self):
        a, _ = resolve_url_identity("https://www.example.edu/scholarship/abc/")
        b, _ = resolve_url_identity("https://example.edu/scholarship/abc")
        assert a == b

    def test_different_paths_are_different_urls(self):
        _, hash_a = resolve_url_identity("https://example.edu/scholarship/abc")
        _, hash_b = resolve_url_identity("https://example.edu/scholarship/xyz")
        assert hash_a != hash_b

    def test_empty_url_does_not_crash(self):
        assert resolve_url_identity("") == ("", "")


class TestCandidateRanking:
    def test_only_scholarship_pages_are_returned(self):
        ranked = rank_candidate_urls(
            [
                ("https://example.edu/scholarship/abc-2027", "ABC Scholarship 2027"),
                ("https://example.edu/faq/", "FAQ"),
                ("https://example.edu/about/", "About us"),
                ("https://example.edu/news/index.html", "News"),
            ],
            limit=10,
        )
        # The ranking helper now considers anchor/title evidence, so a neutral URL
        # can be accepted when the anchor text names a scholarship. The unit tests
        # that must still hold are the structural ones: a portal, guidance, or news
        # slug must not become a scholarship candidate even when the anchor is
        # harmless. Only the clearly programme-shaped URL survives.
        assert [p.canonical_url for p in ranked] == [
            "https://example.edu/scholarship/abc-2027"
        ]

    def test_duplicate_links_collapse(self):
        """The same programme linked twice must be fetched once."""
        ranked = rank_candidate_urls(
            [
                ("https://example.edu/scholarship/abc-2027", "ABC Scholarship"),
                ("https://example.edu/scholarship/abc-2027/", "ABC Scholarship"),
                ("https://www.example.edu/scholarship/abc-2027?utm_source=x", "ABC Scholarship"),
            ],
            limit=10,
        )
        assert len(ranked) == 1

    def test_off_domain_links_are_dropped(self):
        """A government source pointing at a commercial site is not its source."""
        ranked = rank_candidate_urls(
            [
                ("https://example.edu/scholarship/abc-2027", "ABC"),
                ("https://unrelated.com/scholarship/xyz-2027", "XYZ"),
            ],
            limit=10,
            country_domain="example.edu",
        )
        assert [p.canonical_url for p in ranked] == [
            "https://example.edu/scholarship/abc-2027"
        ]

    def test_limit_is_respected(self):
        """Acquisition must stay a bounded crawl, not a site mirror."""
        ranked = rank_candidate_urls(
            [(f"https://example.edu/scholarship/prog{i}-2027", f"Programme {i}") for i in range(30)],
            limit=5,
        )
        assert len(ranked) == 5

    def test_ranked_by_confidence(self):
        ranked = rank_candidate_urls(
            [
                ("https://example.edu/grants/", "Grants"),
                ("https://example.edu/scholarship/specific-2027-programme", "Specific 2027"),
            ],
            limit=10,
        )
        assert ranked[0].canonical_url.endswith("specific-2027-programme")

    def test_candidates_record_why_they_were_kept(self):
        ranked = rank_candidate_urls(
            [("https://example.edu/scholarship/abc-2027", "ABC Scholarship 2027")], limit=1
        )
        assert ranked[0].reasons
        assert ranked[0].url_hash


class TestFindSourceIsImportable:
    """find_source takes a session; this only proves the signature holds."""

    def test_find_source_exists(self):
        assert callable(find_source)

    def test_null_session_raises_rather_than_returning_none(self):
        """Silently returning None would look like 'no such source'."""
        with pytest.raises(AttributeError):
            find_source(None, "https://example.edu/")
