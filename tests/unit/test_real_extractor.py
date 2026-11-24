"""Tests for DeterministicLLMClient.extract_scholarship().

M9 changed name extraction from a prose regex to structural candidates
judged by ``extraction_quality``. These tests assert that change:

- a markdown heading is honoured as heading context (the M8 behaviour that
  was worth keeping)
- an unidentifiable page yields ``None``, not ``"Unknown Scholarship"``
- every result carries its extraction provenance
"""

import pytest

from services.ingestion.real_extractor import DeterministicLLMClient


@pytest.fixture
def client():
    return DeterministicLLMClient()


class TestNameExtraction:
    def test_markdown_heading_is_used(self, client):
        text = "# Amazing Scholarship for Engineers\nSome description"
        verdict = client._extract_name_verdict(text)
        assert verdict.accepted
        assert verdict.normalized_name == "Amazing Scholarship for Engineers"

    def test_heading_alone_is_enough(self, client):
        text = "# Global Tech Scholarship\n\ndeadline: September 30, 2024"
        verdict = client._extract_name_verdict(text)
        assert verdict.accepted

    def test_unidentifiable_page_yields_none_not_a_placeholder(self, client):
        """The M8 failure: a page with no name still produced a name."""
        text = "Read more about our programmes. Click here for details."
        verdict = client._extract_name_verdict(text)
        assert not verdict.accepted
        assert verdict.normalized_name is None

    def test_verdict_always_explains_itself(self, client):
        for text in ("# Some Real Programme 2027", "nothing useful here"):
            assert client._extract_name_verdict(text).reasons


@pytest.mark.parametrize(
    "date_str,expected",
    [
        ("deadline: May 15, 2024", "2024-05-15"),
        ("application deadline: 2024-06-01", "2024-06-01"),
        ("Apply by: 01.07.2024", "2024-07-01"),
        ("deadline 15 May 2024", "2024-05-15"),
        ("deadline: 2024/08/20", "2024-08-20"),
    ],
)
def test_deadline_formats(client, date_str, expected):
    text = f"{date_str}\nOther info"
    deadline = client._extract_deadline(text)
    assert deadline == expected


class TestDeadlineAcrossLanguages:
    """The same field, written the way the countries Polaris crawls write it.

    Malay and German pages stated deadlines that the English-only keyword list
    could not see, and a date like "15. März 2027" failed the month-name pattern
    because "ä" is not [A-Za-z].
    """

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Tarikh tutup permohonan: 31 Disember 2026", "2026-12-31"),
            ("Bewerbungsschluss: 15. März 2027", "2027-03-15"),
            ("The deadline for applications is the 5 June 2027", "2027-06-05"),
            ("The deadline to apply is 3 May 2027", "2027-05-03"),
            (
                "The deadline for submitting application materials for the "
                "program is December 15, 2026 at 23:59",
                "2026-12-15",
            ),
            ("new deadline in May (update: 28/04/2026)", "2026-04-28"),
            ("Applications close on 31 December 2026", "2026-12-31"),
            ("The nomination deadline is 23:59 on Wednesday, Oktober 8, 2025", "2025-10-08"),
        ],
    )
    def test_the_field_is_read_in_its_own_language(self, text, expected):
        assert DeterministicLLMClient()._extract_deadline(text) == expected

    @pytest.mark.parametrize("text", ["deadline 03/04/2026", "deadline 04/03/2026"])
    def test_an_ambiguous_slash_date_is_refused(self, text):
        """03/04/2026 is two different days depending on the writer's country."""
        assert DeterministicLLMClient()._extract_deadline(text) is None


class TestDeadlineWithRealPageWording:
    """Wording that sits between the keyword and the date on real pages.

    These five shapes were all present in staged documents while the extractor
    reported "no deadline published" for 74 of 99 approved records.
    """

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Deadline: Friday 4 December 2026.", "2026-12-04"),
            ("deadline: noon on Tuesday 2nd December 2026", "2026-12-02"),
            ("apply by 1pm (UK time) on Monday 1 June 2026.", "2026-06-01"),
            ("deadline of 5pm (UK time) on Monday 22 March 2027", "2027-03-22"),
            ("Applications open\n- 15 December 2026: Application deadline", "2026-12-15"),
        ],
    )
    def test_weekday_time_and_timezone_filler_is_accepted(self, text, expected):
        assert DeterministicLLMClient()._extract_deadline(text) == expected

    def test_a_date_inside_an_unrelated_clause_is_not_a_deadline(self):
        """The reason the filler is a closed vocabulary rather than "any text"."""
        text = (
            "deadline, i.e. have defended their PhD thesis between "
            "December 2021 and December 2026"
        )
        assert DeterministicLLMClient()._extract_deadline(text) is None

    def test_a_page_that_names_no_date_still_yields_nothing(self):
        assert (
            DeterministicLLMClient()._extract_deadline(
                "Deadline provided by the Admissions Service."
            )
            is None
        )


class TestBenefitNegation:
    """A keyword inside a negation is a statement the benefit is NOT
    provided; recording it as covered misleads applicants."""

    def test_plain_mentions_still_count(self, client):
        benefits = client._extract_benefits(
            "The award covers tuition fees and provides accommodation, "
            "a monthly stipend and health insurance."
        )
        assert benefits["tuition_fee"] is True
        assert benefits["accommodation"] is True
        assert benefits["health_insurance"] is True

    def test_negated_benefits_do_not_count(self, client):
        benefits = client._extract_benefits(
            "Tuition fees are not covered by this award. No accommodation "
            "is provided, and travel costs must be borne by the student."
        )
        assert benefits["tuition_fee"] is False
        assert benefits["accommodation"] is False
        assert benefits["travel_ticket"] is False

    def test_mixed_page_counts_only_real_benefits(self, client):
        benefits = client._extract_benefits(
            "A monthly allowance is paid. Health insurance is not included."
        )
        assert benefits["monthly_allowance"] is True
        assert benefits["health_insurance"] is False


class TestResearchExperienceEvidence:
    def test_bare_research_word_is_not_a_requirement(self, client):
        data = client.extract_scholarship(
            "# Lab Scholarship 2027\n\ndeadline: 2027-01-01\n\n"
            "Join our research laboratory and study robotics.",
            "https://example.com/scholarship",
        )
        assert data["eligibility"]["research_experience"] is None

    def test_explicit_preference_is_extracted(self, client):
        assert (
            client._extract_research_experience(
                "Previous research experience is preferred."
            )
            == "Preferred"
        )

    def test_explicit_requirement_is_extracted(self, client):
        assert (
            client._extract_research_experience(
                "Applicants must have research experience in the field."
            )
            == "Required"
        )


class TestFullExtraction:
    def test_extraction_reports_its_provenance(self, client):
        clean_text = (
            "# Global Tech Scholarship 2027\n\n"
            "deadline: September 30, 2024\n\nGPA: 3.5\nTOEFL: 100\n"
        )
        data = client.extract_scholarship(clean_text, "https://example.com/scholarship")

        assert data["scholarship_name"] == "Global Tech Scholarship 2027"
        meta = data["_extraction"]
        assert meta["name_verdict"]["accepted"] is True
        assert meta["name_verdict"]["confidence"] > 0
        assert meta["source_url"] == "https://example.com/scholarship"

    def test_eligibility_and_benefits_still_extracted(self, client):
        clean_text = """# Global Tech Scholarship 2027

deadline: September 30, 2024

GPA: 3.5
Age limit: 25
TOEFL: 100

Benefits:
- tuition
- accommodation
"""
        data = client.extract_scholarship(clean_text, "https://example.com/scholarship")
        assert data["timeline"]["application_deadline"] == "2024-09-30"
        assert data["eligibility"]["minimum_gpa"] == 3.5
        assert data["eligibility"]["age_limit"] == 25
        assert data["eligibility"]["toefl_required"] is True
        assert data["eligibility"]["minimum_toefl"] == 100
        assert data["benefits"]["tuition_fee"] is True
        assert data["benefits"]["accommodation"] is True

    def test_country_fallback_is_flagged_as_inferred(self, client):
        """A country taken from the source, not the page, is an assumption."""
        clean_text = "# Some Programme 2027\ndeadline: 2026-01-01"
        data = client.extract_scholarship(clean_text, "https://example.com/x", default_country="JP")
        assert data["_extraction"]["country_inferred_from_source"] is True

    def test_country_from_page_is_not_flagged(self, client):
        clean_text = "# Some Programme 2027\ndeadline: 2026-01-01\nOffered by the Japan Foundation in Japan"
        data = client.extract_scholarship(clean_text, "https://example.com/x")
        assert data["_extraction"]["country_inferred_from_source"] is False
