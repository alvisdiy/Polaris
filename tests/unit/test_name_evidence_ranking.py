"""Priority B — scholarship-name evidence ranking (post-M10).

M10 recorded 5 of 12 golden names correct. Four defects produced the other
seven, and each is pinned here against the real page text that exposed it:

1. ranking by raw confidence let a link label outrank the page's own heading
   ("Application procedure & deadlines" won a Fulbright programme page);
2. the site name a CMS appends to a title was published as part of the award
   ("... | KYOTO UNIVERSITY");
3. strings that describe a page were accepted because they are well-formed
   noun phrases ("Frequently Asked Questions", "UNDERGRADUATE SCHOLARSHIPS");
4. when a page's own claim was refused, a link label was promoted to take its
   place — attributing another page's scholarship to this one.

Nothing here weakens the identity gate: a rejection still routes to
PENDING_REVIEW, never to approval.
"""

from __future__ import annotations

import pytest

from services.ingestion.extraction_quality import (
    normalize_scholarship_name,
    score_candidate_name,
    strip_site_suffix,
)
from services.ingestion.real_extractor import DeterministicLLMClient


def _name_of(page_title="", headings=(), anchors=(), body="", looks_like_index=False):
    client = DeterministicLLMClient()
    verdict = client._extract_name_verdict(
        body, page_title, tuple(headings), tuple(anchors), looks_like_index
    )
    return verdict.normalized_name if verdict.accepted else None


class TestSiteSuffixIsNotPartOfTheName:
    """Defect 2. The publisher's name is a fact about the publisher."""

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("Scholarships for international students | KYOTO UNIVERSITY",
             "Scholarships for international students"),
            ("PFP Study Award | Temasek Polytechnic", "PFP Study Award"),
            ("Other scholarship opportunities | KYOTO UNIVERSITY",
             "Other scholarship opportunities"),
            ("DAAD Scholarships - An Overview - DAAD", "DAAD Scholarships - An Overview"),
        ],
    )
    def test_site_name_is_stripped(self, title, expected):
        assert strip_site_suffix(title) == expected

    def test_a_page_type_qualifier_is_not_mistaken_for_a_site_name(self):
        """'DAAD Scholarships - An Overview' keeps its own words."""
        assert strip_site_suffix("DAAD Scholarships - An Overview") == (
            "DAAD Scholarships - An Overview"
        )

    def test_a_funding_noun_in_the_tail_keeps_the_whole_title(self):
        """'Honjo International Scholarship Foundation' names the publisher *and*
        the award, so it is left alone rather than half-truncated."""
        title = "PFP Study Award | Honjo International Scholarship Foundation"
        assert strip_site_suffix(title) == title

    def test_the_published_name_never_contains_the_publisher(self):
        name = _name_of(
            page_title="PFP Study Award | Temasek Polytechnic",
            headings=["PFP Study Award"],
        )
        assert name == "PFP Study Award"
        assert "Temasek" not in name


class TestHeadingOutranksALinkLabel:
    """Defect 1. A link label is a statement about a different page."""

    def test_a_section_heading_does_not_become_the_award_name(self):
        # Real headings and anchors from the Fulbright Scholar Grant page.
        name = _name_of(
            headings=[
                "Fulbright Scholar Grant (including Inter-Country Travel Grant)",
                "Program description",
                "Who can apply?",
                "Application procedure & deadlines",
                "Contact",
            ],
            anchors=["Application procedure & deadlines", "Program description", "Contact"],
        )
        assert name == "Fulbright Scholar Grant (including Inter-Country Travel Grant)"

    def test_another_programmes_name_does_not_outrank_the_page_subject(self):
        # Real headings and anchors from the TP Engineering scholars page.
        name = _name_of(
            page_title="TP-Eng-scholars-2026 | Temasek Polytechnic",
            headings=["SHARE", "TP Engineering scholars 2026"],
            anchors=["Polytechnic Foundation Programme (PFP)", "SHARE"],
        )
        assert name == "TP Engineering scholars 2026"

    def test_a_heading_beats_a_stronger_anchor(self):
        """Confidence breaks ties inside one tier, never across tiers."""
        name = _name_of(
            headings=["NUS Sports Scholarship (Freshmen)"],
            anchors=["NUS Sports Scholarship (Freshmen) - 2026 intake closing soon"],
        )
        assert name == "NUS Sports Scholarship (Freshmen)"


class TestStringsThatDescribeAPageAreNotNames:
    """Defect 3. Naming a document is not naming a scholarship."""

    @pytest.mark.parametrize(
        "candidate",
        [
            "Frequently Asked Questions",
            "Frequently Asked Questions | Honjo International Scholarship Foundation",
            "Cookie Consent",
            "General Scholarship Information",
            "Information for Scholarship Applicants",
            "Privacy Policy",
            "Jump to content",
            "Find scholarships",
            "About us",
        ],
    )
    def test_page_section_headings_are_refused(self, candidate):
        assert score_candidate_name(candidate, in_title=True, in_heading=True).accepted is False

    def test_a_category_label_set_in_capitals_is_refused(self):
        """Real heading from the NUS page. Caps are a typographic convention."""
        assert score_candidate_name(
            "UNDERGRADUATE SCHOLARSHIPS", in_heading=True
        ).accepted is False

    def test_a_title_case_name_is_not_mistaken_for_a_banner(self):
        assert score_candidate_name(
            "NUS Undergraduate Scholarship", in_title=True, in_heading=True
        ).accepted is True

    def test_a_page_with_no_opportunity_in_it_is_refused(self):
        """'Side menu' names an interface region, not a programme."""
        assert score_candidate_name("サイドメニュー（英語）", in_heading=True).accepted is False

    def test_a_navigation_heading_in_japanese_is_refused(self):
        """Real heading from the Kyoto page: 'header primary link (English)'."""
        assert score_candidate_name(
            "ヘッダー プライマリーリンク（英語）", in_heading=True, in_anchor=True
        ).accepted is False

    def test_a_real_japanese_scholarship_name_is_still_accepted(self):
        """The non-Latin script test must not reject genuine Japanese names."""
        verdict = score_candidate_name(
            "日本人大学院生奨学金", in_heading=True, in_title=True
        )
        assert verdict.accepted is True, verdict.reasons

    def test_a_japanese_sentence_is_refused(self):
        """Real heading from the AFS page.

        Japanese writes without spaces, so the word-count prose test sees one
        "word" and lets a complete sentence through at 0.70 confidence.
        """
        sentence = "AFSでの留学には、様々な奨学金がご利用いただけます。"
        assert score_candidate_name(sentence, in_heading=True, in_anchor=True).accepted is False
        assert "sentence" in " ".join(score_candidate_name(sentence).reasons)


class TestALinkLabelCannotStandInForThePage:
    """Defect 4. When the page declines to name itself, so does Polaris."""

    def test_an_faq_page_produces_no_name(self):
        # Real headings and anchors from the Honjo FAQ page.
        name = _name_of(
            page_title="Frequently Asked Questions | Honjo International Scholarship Foundation",
            headings=[
                "Frequently Asked Questions",
                "INDEX",
                "Account (My Page)",
                "Requirements to apply",
                "Applicants information",
            ],
            anchors=["Scholarship for Foreign Students", "Grant for MD/PhD Overseas Study"],
        )
        assert name is None

    def test_a_page_whose_only_claim_is_a_link_label_produces_no_name(self):
        assert _name_of(anchors=["Rhodes Scholarship", "Chevening Scholarships"]) is None

    def test_a_page_with_no_candidates_at_all_produces_no_name(self):
        assert _name_of() is None


class TestRealNamesStillPass:
    """The gate tightened; these must not have been caught by it."""

    @pytest.mark.parametrize(
        "candidate",
        [
            "Loughborough University Sanctuary Scholarships",
            "Cranfield Excellence Merit Scholarships",
            "Commonwealth Shared Scholarship Scheme",
            "Fulbright Scholar Grant (including Inter-Country Travel Grant)",
            "NUS Undergraduate Scholarship",
            "NUS Sports Scholarship (Freshmen)",
            "PFP Study Award",
            "TP Engineering scholars 2026",
            "DAAD Scholarships - An Overview",
            "The Fulbright / Kennedy Center Fellowship for Performing Arts And Science",
            "日本人大学院生奨学金",
        ],
    )
    def test_a_real_name_is_accepted_as_a_heading(self, candidate):
        verdict = score_candidate_name(candidate, in_title=True, in_heading=True)
        assert verdict.accepted is True, verdict.reasons
        assert verdict.normalized_name == candidate

    def test_the_long_name_about_performing_arts_is_not_read_as_a_sentence(self):
        """A long canonical name is a name. A long non-canonical string is prose."""
        verdict = score_candidate_name(
            "The Fulbright / Kennedy Center Fellowship for Performing Arts And Science",
            in_heading=True,
        )
        assert verdict.accepted is True
        assert "reads as a sentence" not in verdict.reasons

    def test_normalisation_is_unaffected_by_the_site_strip(self):
        """identity_key must not change shape because a name lost its publisher."""
        assert normalize_scholarship_name("PFP Study Award | Temasek Polytechnic") == (
            "pfp study award | temasek polytechnic"
        )
