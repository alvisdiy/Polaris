"""Priority C — the two vocabulary gaps stay open (ADR-018).

Both were recorded by M10 as defects to fix. Neither is: the corpus evidence
in `scripts/p10_vocabulary_gap.py` says the mapping would be wrong. These
tests pin the decisions so neither gap can be closed by a well-meaning alias,
and so a future contributor reads the reason before adding one.

The point of each test is not "the current behaviour is fine". It is "the
behaviour is a decision with evidence behind it, not an oversight".
"""

from __future__ import annotations

import pytest

from services.domain import vocabulary as vocab
from services.ingestion.real_extractor import DeterministicLLMClient


class TestC1UndergraduateIsNotBachelor:
    """ADR-018 C1.

    "undergraduate" appears in 109 of 269 stored documents, but as site
    navigation or as the programme a student enters. The stored NUS page
    states its eligibility as "local Polytechnic Diploma ... or equivalent"
    while calling the programme "undergraduate". Mapping the word to Bachelor
    would tell a student they hold a qualification their own source denies.
    """

    def test_undergraduate_is_not_an_alias(self):
        assert "undergraduate" not in vocab.DEGREE.aliases

    def test_no_alias_resolves_to_bachelor_by_way_of_undergraduate(self):
        for alias, canonical in vocab.DEGREE.aliases.items():
            assert "undergraduate" not in alias, (
                f"{alias!r} maps to {canonical}; ADR-018 refuses this mapping"
            )

    def test_the_canonical_vocabulary_is_unchanged(self):
        assert vocab.DEGREE.order == (
            "Bachelor",
            "Exchange",
            "Master",
            "PhD",
            "Short Course",
        )

    def test_a_page_that_only_says_undergraduate_yields_no_degree(self):
        client = DeterministicLLMClient()
        result = client.extract_scholarship(
            clean_text=(
                "The NUS Undergraduate Scholarship is open to local Polytechnic "
                "Diploma holders matriculating into a full-time undergraduate "
                "programme at NUS."
            ),
            source_url="https://nus.edu.sg/oam/scholarships/nus-undergraduate-scholarship",
            page_title="NUS Undergraduate Scholarship",
            headings=("NUS Undergraduate Scholarship",),
        )
        assert result["degree"] is None

    def test_the_diploma_wording_is_kept_as_evidence(self):
        """A NULL with evidence reads as a decision; a bare NULL reads as a bug."""
        client = DeterministicLLMClient()
        result = client.extract_scholarship(
            clean_text=(
                "Eligibility: local Polytechnic Diploma, International "
                "Baccalaureate Diploma or equivalent qualifications."
            ),
            source_url="https://nus.edu.sg/oam/scholarships/nus-undergraduate-scholarship",
            page_title="NUS Undergraduate Scholarship",
        )
        meta = result["_extraction"]
        assert result["degree"] is None
        assert meta["unmapped_qualification"] == "diploma"

    def test_an_explicit_bachelors_wording_still_resolves(self):
        """The decision refuses the alias, not the mapping itself."""
        assert vocab.normalize("degree", "bachelor degree") == "Bachelor"


class TestC2ComprehensiveCostIsNotFullyFunded:
    """ADR-018 C2.

    Only 1 of 25 documents containing a cost-coverage phrase states an
    award's own funding value; the rest describe student loans, sponsors and
    deposit waivers. "Fully Funded" is a completeness claim the Cranfield
    sentence never makes, and the components are already modelled as
    structured benefits.
    """

    def test_no_cost_list_is_an_alias_for_fully_funded(self):
        for alias in vocab.FUNDING_TYPE.aliases:
            assert "tuition fees" not in alias, (
                f"{alias!r} would map a cost list to a completeness claim; "
                "ADR-018 refuses it"
            )

    def test_the_funding_vocabulary_is_the_deliberate_set(self):
        """The controlled set is now pinned explicitly, including its growth.

        ADR-018 originally froze this vocabulary at three values so a cost list
        could never become a completeness claim. Scholarship-discovery expansion
        widened it deliberately, because three values forced three genuinely
        different real-world awards into one bucket — most visibly, a page
        promising to *waive tuition in full* and a page covering *fees only*
        both published as "Tuition Only".

        What ADR-018 protects is unchanged and still enforced by
        `test_no_cost_list_is_an_alias_for_fully_funded`: the new values are
        coverage categories the page must state, not a looser route to
        "Fully Funded". The two tests below pin that distinction so a future
        widening cannot quietly reintroduce the original defect.
        """
        assert vocab.FUNDING_TYPE.order == (
            "Fully Funded",
            "Partial Funded",
            "Tuition Only",
            "Tuition Waiver",
            "Stipend Only",
            "Living Allowance",
            "Travel Support",
            "Research Funding",
        )

    def test_unknown_funding_is_still_null_and_not_a_vocabulary_value(self):
        """"We did not find evidence" must not become a publishable string.

        V0.1 found 18 records publishing "Fully Funded" with `source_value =
        NULL`. The remedy was to leave `funding_type` NULL when the page does
        not state a coverage claim; adding categories must not reopen that.
        """
        assert "Unknown" not in vocab.FUNDING_VALUES
        assert "Other" not in vocab.FUNDING_VALUES

    def test_a_tuition_waiver_is_not_reported_as_tuition_only(self):
        """The distinction the widening exists to preserve."""
        client = DeterministicLLMClient()
        result = client.extract_scholarship(
            clean_text=(
                "Applicants receive a full tuition waiver for the duration of "
                "the programme."
            ),
            source_url="https://example.org/scholarship/waiver",
            default_country="GB",
        )
        assert result["funding_type"] == "Tuition Waiver"
        evidence = result["_extraction"]["funding_evidence"]
        assert evidence["canonical"] == "Tuition Waiver"
        assert "waiver" in evidence["statement"].lower()

    def test_the_real_cranfield_wording_yields_no_funding_type(self):
        """Verbatim from the stored Cranfield Commonwealth page."""
        client = DeterministicLLMClient()
        result = client.extract_scholarship(
            clean_text=(
                "At a glance Funding value All tuition fees, travel and living "
                "costs Suitable for Applicants from Rest of world Deadline "
                "09 Dec 2025."
            ),
            source_url=(
                "https://www.cranfield.ac.uk/funding/funding-opportunities/"
                "commonwealth-shared-scholarship-scheme"
            ),
            page_title="Commonwealth Shared Scholarship Scheme",
            headings=("Commonwealth Shared Scholarship Scheme",),
        )
        assert result["funding_type"] is None

    def test_the_wording_is_still_reported_to_the_reviewer(self):
        client = DeterministicLLMClient()
        result = client.extract_scholarship(
            clean_text="Funding value All tuition fees, travel and living costs.",
            source_url=(
                "https://www.cranfield.ac.uk/funding/funding-opportunities/"
                "commonwealth-shared-scholarship-scheme"
            ),
            page_title="Commonwealth Shared Scholarship Scheme",
        )
        statement = result["_extraction"].get("unmapped_funding_statement")
        assert statement and "tuition fees" in statement.casefold(), (
            "a NULL funding_type must still carry the source wording, or a "
            "reviewer cannot tell a failed extraction from an unrecognised one"
        )
        assert result["funding_type"] is None

    def test_a_recognised_alias_is_not_reported_as_unmapped(self):
        """The evidence is only for wording the vocabulary cannot carry."""
        client = DeterministicLLMClient()
        result = client.extract_scholarship(
            clean_text="The award is a full tuition waiver for the duration.",
            source_url="https://example.edu/award",
            page_title="Example Award",
        )
        assert result["funding_type"] == "Tuition Waiver"
        assert result["_extraction"]["unmapped_funding_statement"] is None

    def test_a_student_loan_is_not_the_scholarships_funding(self):
        """The other 24 of 25 corpus matches are loans and sponsors.

        "Lendwise Student Loan ... can cover tuition fees and living
        expenses" is money the student arranges. Recording it as the award's
        funding evidence would send a reviewer to the wrong sentence.
        """
        client = DeterministicLLMClient()
        result = client.extract_scholarship(
            clean_text=(
                "Lendwise offer affordable student loans ranging from £5,000 to "
                "£100,000 which can cover tuition fees and living expenses."
            ),
            source_url="https://www.cranfield.ac.uk/funding",
            page_title="Funding",
        )
        assert result["funding_type"] is None
        assert result["_extraction"]["unmapped_funding_statement"] is None

    @pytest.mark.parametrize(
        "wording,expected",
        [
            ("fully funded", "Fully Funded"),
            ("complete funding", "Fully Funded"),
            # Was "Tuition Only" before the taxonomy widened. A waiver of the
            # whole tuition fee is a different promise from covering fees only,
            # and collapsing them was the reason the value was separated.
            ("tuition waiver", "Tuition Waiver"),
            ("tuition only", "Tuition Only"),
            ("stipend only", "Stipend Only"),
            ("living allowance", "Living Allowance"),
            ("travel grant", "Travel Support"),
            ("research grant", "Research Funding"),
            ("partial funding", "Partial Funded"),
        ],
    )
    def test_the_existing_aliases_still_work(self, wording, expected):
        assert vocab.normalize("funding_type", wording) == expected


class TestTheVocabularyStaysAControlledList:
    """The guarantees ADR-018 depends on, checked rather than assumed."""

    def test_both_vocabularies_are_still_closed_sets(self):
        assert set(vocab.DEGREE.order) == {
            "Bachelor",
            "Exchange",
            "Master",
            "PhD",
            "Short Course",
        }
        assert set(vocab.FUNDING_TYPE.order) == {
            "Fully Funded",
            "Partial Funded",
            "Tuition Only",
            "Tuition Waiver",
            "Stipend Only",
            "Living Allowance",
            "Travel Support",
            "Research Funding",
        }

    def test_an_out_of_vocabulary_value_is_refused_not_guessed(self):
        from services.domain.vocabulary import InvalidVocabularyValue

        with pytest.raises(InvalidVocabularyValue):
            vocab.validate("degree", "Undergraduate")

    def test_an_unrecognised_wording_normalises_to_none(self):
        assert vocab.normalize("degree", "undergraduate programme") is None
