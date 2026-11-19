"""Unit tests for the shared page-section label vocabulary."""

from __future__ import annotations

import pytest

from services.domain.page_labels import section_label


class TestItRecognisesSections:
    @pytest.mark.parametrize(
        "text",
        [
            "Topics",
            "JSPS Topics",
            "Fellowship Categories",
            "2027-2028 Fellowship Categories",
            "Fees and funding",
            "Guidelines on tuition fees",
            "Tuition fees for taught courses 2027-2028",
            "3. Interview",
            "1. Application Methods",
            "Academic Year 2026",
            "970,000 registrants",
            "About the Foundation",
            "Topics | Japan Society for the Promotion of Science",
        ],
    )
    def test_a_section_is_a_section(self, text):
        assert section_label(text) is not None

    def test_the_match_names_what_it_objected_to(self):
        assert section_label("JSPS Topics") == "JSPS Topics"


class TestItLeavesRealNamesAlone:
    @pytest.mark.parametrize(
        "text",
        [
            "Dr Mai Yamani Scholarship",
            "MEXT Scholarship for Research Students",
            "Chevening Scholarships",
            "DAAD Funding Programme",
            "Postgraduate Future Leaders Scholarship",
            "Fulbright US-ASEAN Visiting Scholar Program",
            "Loughborough Computer Studies Award",
            "Sport Scholarships",
            "Eiffel Excellence Scholarship Program",
        ],
    )
    def test_a_name_is_a_name(self, text):
        assert section_label(text) is None

    def test_a_singular_scholarship_title_is_not_a_section(self):
        assert section_label("Hilde Domin Programme") is None

    def test_empty_text_is_not_a_label(self):
        assert section_label("") is None
        assert section_label("   ") is None
