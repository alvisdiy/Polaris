"""Unit tests for extraction quality — the M9 gate on fabricated identities.

Two properties matter more than any individual case:

1. Portal chrome never becomes a scholarship name (the M8 failure).
2. A real scholarship name, in any language, is not thrown away with it.

Both are asserted here as behaviour, not as a blacklist length.
"""

from __future__ import annotations

import pytest

from services.ingestion.extraction_quality import (
    CONFIDENCE_ACCEPT,
    ExtractionVerdict,
    has_identity_tokens,
    normalize_scholarship_name,
    score_candidate_name,
    substantive_words,
)

# Names the M8 extractor actually produced into the knowledge base.
M8_PORTAL_FRAGMENTS = [
    "Unknown Scholarship",
    "Number of Scholarship",
    "Amount of Scholarship",
    "Das Program",
    "Bitte entnehmen Sie der Program",
    "At a glance Grant",
    "Grant",
    "Scholarship",
    "Promovierende ein besonderes Program",
]

# Real scholarship names from the current approved knowledge base.
REAL_NAMES = [
    "MEXT Scholarship for Research Students",
    "Monbukagakusho Scholarship 2027",
    "Chevening Scholarships",
    "DAAD Helmut-Schmidt-Programme",
    "DAAD Development-Related Postgraduate Courses (EPOS)",
    "Honjo International Scholarship",
    "LPDP Beasiswa Reguler (Master)",
    "Fulbright Foreign Student Program",
    "Eiffel Scholarship",
    "Australia Awards",
    "Chinese Government Scholarship",
]


class TestGenericNamesAreRejected:
    @pytest.mark.parametrize("name", M8_PORTAL_FRAGMENTS)
    def test_portal_fragment_rejected_even_as_page_title(self, name):
        """The strongest possible context must not rescue a generic string."""
        verdict = score_candidate_name(name, in_title=True, in_heading=True, in_anchor=True)
        assert not verdict.accepted, f"{name!r} must not be accepted"
        assert verdict.normalized_name is None

    @pytest.mark.parametrize("name", M8_PORTAL_FRAGMENTS)
    def test_rejected_candidate_reports_a_reason(self, name):
        verdict = score_candidate_name(name, in_heading=True)
        assert verdict.reasons, "every rejection must be explainable"

    def test_rejection_reports_confidence_below_threshold(self):
        """A refused string must not be reported as high-confidence."""
        verdict = score_candidate_name("Unknown Scholarship", in_title=True, in_heading=True)
        assert verdict.confidence < CONFIDENCE_ACCEPT


class TestRealNamesAreAccepted:
    @pytest.mark.parametrize("name", REAL_NAMES)
    def test_real_name_accepted_with_page_context(self, name):
        verdict = score_candidate_name(name, in_title=True, in_heading=True)
        assert verdict.accepted, f"{name!r} was rejected: {verdict.reasons}"
        assert verdict.normalized_name == name
        assert verdict.confidence >= CONFIDENCE_ACCEPT

    @pytest.mark.parametrize("name", REAL_NAMES)
    def test_real_name_accepted_on_anchor_alone(self, name):
        """Link labels are how names appear on official index pages."""
        verdict = score_candidate_name(name, in_anchor=True)
        assert verdict.accepted, f"{name!r} rejected from an anchor: {verdict.reasons}"

    def test_multilingual_name_accepted(self):
        verdict = score_candidate_name("日本政府 Scholarship 2027", in_heading=True)
        assert verdict.accepted

    def test_leading_capital_alone_is_not_identity(self):
        """English title-case capitalises every content word.

        "Fully Funded Scholarship" capitalises three words and names nothing.
        """
        assert not score_candidate_name("Fully Funded Scholarship", in_heading=True).accepted
        assert not score_candidate_name("Available Scholarships", in_heading=True).accepted


class TestPageContextMatters:
    def test_body_prose_without_identity_is_rejected(self):
        verdict = score_candidate_name("Some scholarship information for students")
        assert not verdict.accepted
        assert "no title/heading/anchor context" in " ".join(verdict.reasons)

    def test_index_page_caps_confidence(self):
        detail = score_candidate_name("Eiffel Scholarship", in_title=True, in_heading=True)
        index = score_candidate_name(
            "Eiffel Scholarship", in_title=True, in_heading=True, page_is_portal_index=True
        )
        assert index.confidence < detail.confidence

    def test_empty_and_blank_candidates_rejected(self):
        for candidate in (None, "", "   ", "\n\t"):
            assert not score_candidate_name(candidate, in_title=True).accepted


class TestIdentityTokens:
    def test_year_is_structural_identity(self):
        assert has_identity_tokens("Monbukagakusho 2027")[0]

    def test_acronym_is_structural_identity(self):
        assert has_identity_tokens("MEXT Scholarship")[0]

    def test_non_latin_script_is_structural_identity(self):
        assert has_identity_tokens("장학금")[0]

    def test_bare_noun_has_no_identity(self):
        assert not has_identity_tokens("Scholarship")[0]
        assert not has_identity_tokens("Available Grants")[0]

    def test_substantive_words_excludes_generic_vocabulary(self):
        assert substantive_words("Fully Funded Scholarship") == []
        assert "chevening" in substantive_words("Chevening Scholarships")


class TestNormalization:
    def test_case_and_punctuation_collapse(self):
        a = normalize_scholarship_name("  MEXT Scholarship,  ")
        b = normalize_scholarship_name("mext scholarship")
        assert a == b

    def test_whitespace_collapse(self):
        assert normalize_scholarship_name("Eiffel   Scholarship") == normalize_scholarship_name(
            "Eiffel Scholarship"
        )


class TestVerdictShape:
    def test_explain_is_always_populated(self):
        good = score_candidate_name("Eiffel Scholarship", in_title=True)
        bad = score_candidate_name("Unknown Scholarship", in_heading=True)
        assert isinstance(good.explain(), str) and good.explain()
        assert isinstance(bad.explain(), str) and bad.explain()

    def test_verdict_is_plain_dataclass(self):
        verdict = ExtractionVerdict(True, 0.9, ["ok"], "X")
        assert verdict.accepted and verdict.normalized_name == "X"
