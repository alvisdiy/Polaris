"""V0.1.1 Steps 7 and 8 — the listing guard, and the pages it must not touch.

Two halves, because the failure modes are opposite and a guard that only gets
the first right is worthless:

* **The two real publications** (Step 7). Both pages that reached the public API
  in V0.1 must now be ``HIGH_CONFIDENCE_LISTING``. These fixtures are
  *generated* from the stored raw documents by
  ``scripts/v01_gen_listing_fixtures.py``, so they reproduce the exact
  page-intent verdicts that permitted publication — each test asserts that
  verdict before asserting the guard's. A hand-written approximation would let
  these tests pass while the guard still failed on the real page.
* **The negative set** (Step 8). Legitimate scholarship titles and shapes must
  all still extract. A guard that rejects a real award is worse than no guard,
  because it is silent about what it lost.

Everything here is offline. No test touches the network.
"""

from __future__ import annotations

import pytest

from services.exploration.listing_guard import (
    ListingGuard,
    ListingVerdict,
    classify_listing_page,
)
from services.exploration.page_intent import PageIntent, classify_page_intent
from tests.fixtures.listing_pages import FIXTURES, fixture


def _guard(name: str, **overrides):
    """Run the production chain: fixture -> page intent -> listing guard."""
    data = dict(fixture(name))
    data.update(overrides)
    intent = classify_page_intent(
        url=data["url"],
        page_title=data["title"],
        headings=data["headings"],
        anchors=data["anchors"],
        text=data["text"],
    )
    guard = classify_listing_page(
        page_title=data["title"],
        headings=data["headings"],
        anchors=data["anchors"],
        text=data["text"],
        intent=intent,
    )
    return data, intent, guard


def _page(title: str, headings, anchors, text: str):
    """Guard a page shape with no fixture, for the negative set."""
    return classify_listing_page(
        page_title=title, headings=headings, anchors=anchors, text=text
    )


# ---------------------------------------------------------------- Step 7
# The two real publications.


class TestRealFailuresAreBlocked:
    def test_prospects_recruitment_page_is_high_confidence_listing(self):
        """Failure #1: an advertising page that produced "970,000 registrants"."""
        data, intent, guard = _guard("prospects")

        assert intent.intent == PageIntent.UNKNOWN, (
            "the fixture must reproduce the UNKNOWN verdict that let this page "
            "through, otherwise this test does not exercise the real bypass"
        )
        assert intent.confidence == 0.0
        assert guard.verdict == ListingVerdict.HIGH_CONFIDENCE_LISTING
        assert "metric_heading_no_opportunity_claim" in guard.signals
        assert guard.should_extract is False

    def test_wemakescholars_aggregator_page_is_high_confidence_listing(self):
        """Failure #2: "190+ Post Doc scholarships 2026-27" scored as DETAIL."""
        data, intent, guard = _guard("wemakescholars")

        assert intent.intent == PageIntent.SCHOLARSHIP_DETAIL, (
            "the fixture must reproduce the DETAIL verdict that let this page "
            "through, otherwise this test does not exercise the real bypass"
        )
        assert intent.confidence > 0.5
        assert guard.verdict == ListingVerdict.HIGH_CONFIDENCE_LISTING
        assert guard.should_extract is False

    def test_both_real_failures_carry_at_least_one_independent_signal(self):
        """The aggregator is not blocked by its title alone.

        Its title could be reworded tomorrow; the 78 programme links and the 78
        individual award headings could not. Dropping the title must not let it
        through.
        """
        _data, _intent, guard = _guard(
            "wemakescholars", title="Study opportunities abroad"
        )

        assert "repeated_award_headings" in guard.signals
        assert "programme_link_spike" in guard.signals
        assert guard.verdict == ListingVerdict.HIGH_CONFIDENCE_LISTING

    @pytest.mark.parametrize("name", sorted(FIXTURES))
    def test_no_real_failure_is_extracted(self, name):
        _d, _i, guard = _guard(name)
        assert guard.should_extract is False, f"{name} would still be extracted"

    @pytest.mark.parametrize("name", sorted(FIXTURES))
    def test_the_published_names_reproduce_the_v01_failure(self, name):
        """The names V0.1 actually served, from the fixture, not from memory."""
        assert fixture(name)["published_name_in_v01"]

    def test_the_reason_is_the_documented_constant(self):
        assert ListingGuard.REASON == "LISTING_PAGE_DETECTED"

    def test_the_verdict_records_the_signals_that_produced_it(self):
        """Evidence has to be replayable by whoever reads the frontier later."""
        payload = _guard("wemakescholars")[2].to_dict()
        assert payload["verdict"] == ListingVerdict.HIGH_CONFIDENCE_LISTING
        assert isinstance(payload["signals"], list) and payload["signals"]
        assert payload["title"].startswith("190+ Post Doc scholarships")
        assert payload["programme_links"] >= 25
        assert payload["award_headings"] >= 8


# ---------------------------------------------------------------- Step 2
# Signal family A — the count and listing-construction headings the brief names.


class TestListingHeadingShapes:
    @pytest.mark.parametrize(
        "title",
        [
            "190+ Post Doc Scholarships",
            "62+ Masters Scholarships",
            "50+ Fully Funded Scholarships",
            "100 Scholarships",
            "1000 Scholarships",
            "1,000+ Scholarships",
            "25 Bursaries",
            "300 Graduate Scholarships",
        ],
    )
    def test_count_headings_are_blocked(self, title):
        assert _page(title, [title], [], "").verdict == (
            ListingVerdict.HIGH_CONFIDENCE_LISTING
        )

    @pytest.mark.parametrize(
        "title",
        [
            "2026 Global Korea Scholarship(GKS) program for Undergraduate Degrees",
            "2027 Fulbright Grant",
            "2026 Erasmus+ Scholarship",
            "2025 Chevening Award",
        ],
    )
    def test_an_intake_year_is_not_a_quantity(self, title):
        """"2026 Global Korea Scholarship" is one award, not 2,026 of them.

        The count patterns read a leading year as a count and the guard refused
        a live MOFA Korea announcement whose intent the classifier had already
        called SCHOLARSHIP_DETAIL.
        """
        guard = _page(title, [title], [], "")
        assert "count_heading" not in guard.signals, guard.signals
        assert guard.verdict != ListingVerdict.HIGH_CONFIDENCE_LISTING

    @pytest.mark.parametrize(
        "title",
        [
            "Scholarships 2026-27",
            "Scholarships for International Students",
            "Scholarships by degree",
            "Postgraduate Scholarships 2026-27",
        ],
    )
    def test_plural_listing_constructions_are_blocked(self, title):
        assert _page(title, [title], [], "").verdict == (
            ListingVerdict.HIGH_CONFIDENCE_LISTING
        )


# ---------------------------------------------------------------- Step 3
# Signal family B — structure.


class TestStructuralSignals:
    def test_repeated_award_headings_alone_are_ambiguous_not_blocked(self):
        """One signal is never enough on its own; the pair is the signal."""
        guard = classify_listing_page(
            page_title="Scholarships",
            headings=[f"Scholarship {i}" for i in range(30)],
            anchors=["nav"],
            intent=None,
        )
        assert "repeated_award_headings" in guard.signals
        assert "programme_link_spike" not in guard.signals
        assert guard.verdict == ListingVerdict.AMBIGUOUS
        assert guard.should_extract is True

    def test_repeated_award_headings_with_a_link_spike_are_blocked(self):
        guard = classify_listing_page(
            page_title="Awards",
            headings=[f"Scholarship {i}" for i in range(30)],
            anchors=[f"Scholarship programme {i}" for i in range(30)],
            intent=None,
        )
        assert guard.verdict == ListingVerdict.HIGH_CONFIDENCE_LISTING

    def test_an_index_page_is_blocked_even_used_standalone(self):
        intent = classify_page_intent(
            url="https://example.org/scholarships",
            page_title="Scholarships",
            headings=["Scholarship A", "Scholarship B", "Scholarship C"],
            anchors=["Scholarship A", "Scholarship B", "Scholarship C",
                     "Scholarship D", "Scholarship E", "Scholarship F"],
            text="Apply for our scholarships.",
        )
        assert intent.intent == PageIntent.SCHOLARSHIP_INDEX
        guard = classify_listing_page(
            page_title="Scholarships",
            headings=["Scholarship A", "Scholarship B", "Scholarship C"],
            anchors=[],
            text="",
            intent=intent,
        )
        assert guard.should_extract is False


# ---------------------------------------------------------------- Step 6
# The tri-state contract.


class TestTriStateContract:
    def test_ambiguous_pages_still_extract(self):
        """Ambiguity must never become rejection, or recall dies silently."""
        guard = classify_listing_page(
            page_title="Fees and scholarships",
            headings=["Bursaries"] * 12,
            anchors=["nav"] * 5,
            intent=None,
        )
        assert guard.verdict == ListingVerdict.AMBIGUOUS
        assert guard.should_extract is True

    def test_a_clean_detail_page_is_not_listing(self):
        guard = _page(
            "Chevening ASEAN Scholarship",
            ["Chevening ASEAN Scholarship", "Benefits"],
            ["Apply"],
            "A one-year master's degree in the UK.",
        )
        assert guard.verdict == ListingVerdict.NOT_LISTING
        assert guard.should_extract is True

    def test_an_empty_page_is_not_blocked(self):
        """No evidence must not mean rejection."""
        guard = classify_listing_page(page_title="", headings=[], anchors=[], text="")
        assert guard.verdict == ListingVerdict.NOT_LISTING
        assert guard.should_extract is True

    def test_only_high_confidence_listing_blocks_extraction(self):
        assert ListingVerdict.HIGH_CONFIDENCE_LISTING != ListingVerdict.AMBIGUOUS
        for title in ("Chevening ASEAN Scholarship", ""):
            assert classify_listing_page(page_title=title).should_extract is True


# ---------------------------------------------------------------- Step 8
# False-positive protection. Each case below is a real title or a real shape.


class TestLegitimatePagesAreNotBlocked:
    @pytest.mark.parametrize(
        "title",
        [
            # Step 8 case 1 — a year is not a count.
            "Scholarship 2026",
            "MEXT Scholarship for Research Students 2026",
            "Einstein Fellowship 2026",
            "Wellcome Trust Early Career Doctoral Fellowship 2026",
            "Chevening Scholarships 2027",
            "Commonwealth PhD Scholarships 2027",
            "Humboldt Research Fellowship for Postdoctoral Researchers 2027",
            "Fulbright Foreign Student Program 2027",
            "Banting Postdoctoral Fellowships 2026",
            "DAAD Research Grants - Doctoral Programmes in Germany",
            "Marie Curie Postdoctoral Fellowship 2026",
            "PM Yasasvi Post-Matric Scholarship for OBC Students",
            # Step 8 case 2 — small numbers name seats, not a collection.
            "3 PhD Studentships",
            "5 Graduate Scholarships",
            "Announcing 3 PhD Studentships within Royal Holloway funded "
            "by the AHRC Doctoral Landscape Awards",
            # A large number inside a real award's name.
            "PhD Studentship in Medicinal Chemistry",
        ],
    )
    def test_real_award_titles_are_not_blocked(self, title):
        guard = _page(title, [title], ["Apply"], "")
        assert guard.verdict == ListingVerdict.NOT_LISTING, (
            f"false positive on a real award title: {title} "
            f"({guard.signals})"
        )
        assert guard.should_extract is True

    def test_a_university_detail_page_with_many_navigation_links(self):
        """Step 8 case 3: many links alone must never reject.

        Measured real page — studyinjapan.go.jp MEXT, an already-published V0.1
        record, with a large navigation and funding vocabulary throughout.
        """
        guard = _page(
            "Japanese Government (MEXT) Scholarship｜Study in Japan Official Website",
            ["Japanese Government (MEXT) Scholarship", "Current Students",
             "Giving to UTokyo", "Education"],
            [f"nav link {i}" for i in range(60)]
            + ["Scholarships", "About Japan", "Living in Japan"],
            "Tuition exempted. Round-trip travel expenses (airfare) provided. "
            "Monthly payments of 143,000-145,000 yen.",
        )
        assert guard.should_extract is True
        assert guard.verdict == ListingVerdict.NOT_LISTING

    def test_a_detail_page_with_related_links_to_other_scholarships(self):
        """Step 8 case 4: a few related links is not a card list."""
        guard = _page(
            "International Postgraduate Scholarship 2027",
            ["International Postgraduate Scholarship 2027"],
            ["Scholarship for Ghana", "Scholarship for Nigeria",
             "Scholarship for Kenya", "Apply", "Contact"],
            "Applications are open. Application deadline: 30 June 2027. "
            "Tuition fee support and living allowance.",
        )
        assert guard.should_extract is True

    def test_a_single_opportunity_programme_page(self):
        """Step 8 case 5. Also the USTEP calibration case.

        USTEP is UNKNOWN/0.0 with zero funding mentions and is a real
        opportunity. A guard that rejected UNKNOWN-plus-no-funding would have
        killed a published record.
        """
        guard = _page(
            "University-wide Student Exchange Program (USTEP) Type U",
            ["Current Students",
             "University-wide Student Exchange Program (USTEP) Type U"],
            ["Skip to content", "Contact", "日本語", "Giving to UTokyo",
             "Education", "About UTokyo"],
            "USTEP Type U is the university-wide exchange programme for "
            "undergraduate students. Apply through your faculty.",
        )
        assert guard.should_extract is True

    def test_the_singular_for_award_construction_is_not_a_listing(self):
        """Regression found while building the guard.

        Honjo's real page is titled "Scholarship for Foreign Students | Honjo
        International Scholarship Foundation". A singular "Scholarship for ..."
        pattern rejected it; only the plural names a set.
        """
        guard = _page(
            "Scholarship for Foreign Students | Honjo International "
            "Scholarship Foundation",
            ["Scholarship for Foreign Students"],
            ["Apply", "Donate", "About us"],
            "Application deadline: 30 April. Eligibility: foreign students "
            "enrolled at a Japanese university. Benefit: monthly stipend of "
            "150,000 yen.",
        )
        assert guard.should_extract is True

    def test_a_metric_figure_is_not_blocked_when_the_page_claims_an_opportunity(self):
        """The metric signal's conjunction, and why each clause is there.

        The bare "540k magazine recipients" heading is what the Prospects page
        had. Here the page also carries a funding claim, so it is not blocked —
        a real opportunity page may legitimately print a reach figure.
        """
        guard = _page(
            "Chevening ASEAN Scholarship",
            ["540k magazine recipients", "Our reach"],
            ["Apply", "Contact"],
            "A one-year master's degree in the UK. Monthly stipend paid. "
            "Tuition fees covered.",
        )
        assert guard.verdict == ListingVerdict.NOT_LISTING

    def test_a_metric_figure_with_no_opportunity_claim_is_blocked(self):
        """The Prospects shape, isolated so the conjunction is visible."""
        guard = _page(
            "Alumni Fund Annual Report",
            ["540k magazine recipients", "70% uplift.", "2.1 million"],
            ["Skip to content", "Donate", "Contact"],
            "Our alumni magazine reaches 540k recipients each year. "
            "Support the fund today.",
        )
        assert guard.verdict == ListingVerdict.HIGH_CONFIDENCE_LISTING
        assert "metric_heading_no_opportunity_claim" in guard.signals

    def test_trailing_punctuation_in_a_metric_heading_still_counts(self):
        """The real stored headings are "970,000 registrants." with the stop
        inside the heading. A ``\\s*$`` anchor would miss every one of them."""
        guard = _page(
            "Annual Report",
            ["970,000 registrants.", "540k magazine recipients."],
            ["Contact"],
            "Reach our audience.",
        )
        assert "metric_heading_no_opportunity_claim" in guard.signals

    def test_only_the_first_heading_is_read_for_the_listing_claim(self):
        """Nav menus on every university page contain the word "Scholarships".

        Measured on the MEXT page: scanning deeper headings rejected a real,
        already-published scholarship.
        """
        guard = _page(
            "Japanese Government (MEXT) Scholarship",
            ["Japanese Government (MEXT) Scholarship",
             "100+ Other Scholarships"],
            ["Apply"],
            "Tuition exempted. Monthly stipend of 143,000 yen.",
        )
        assert guard.verdict == ListingVerdict.NOT_LISTING
