"""Declared award levels: the set a page states under a level label."""

from __future__ import annotations

from services.domain.degree_levels import declared_award_levels

OTSUTA = """## Otsuka Toshimi Scholarship Foundation Scholarship

- Academic level:
- Doctoral degree program Master's degree program Bachelor's degree program
- Special notes:
Undergraduate Students (3rd and 4th year)

## Basic information
"""

TAMA = """## Tama Art University Scholarship

Academic level:
:   Master's degree program
    Bachelor's degree program

Contents
"""


def test_multiple_levels_in_a_labelled_block_are_returned():
    assert declared_award_levels(OTSUTA) == ["Bachelor", "Master", "PhD"]


def test_levels_rendered_on_one_line_are_separated():
    assert declared_award_levels(TAMA) == ["Bachelor", "Master"]


def test_single_level_is_left_to_the_single_value_extractor():
    # One level is what ``degree`` records. Returning it here would write the
    # same fact twice through two paths.
    text = "Academic level:\n:   Master's degree program\n\nContents\n"
    assert declared_award_levels(text) == []


def test_applicant_eligibility_list_is_not_the_award_levels():
    # "an existing Master's degree ... a Doctoral qualification" describes the
    # applicant. Publishing it as the award's levels would filter wrongly.
    text = (
        "Applicants must hold an existing Master's degree or a Doctoral "
        "qualification in a relevant field.\n\nEligibility: see above\n"
    )
    assert declared_award_levels(text) == []


def test_block_stops_at_the_next_label():
    # The levels after "Special notes:" belong to a different field. A block
    # that kept reading would collect them.
    text = (
        "Academic level:\n:   Master's degree program\n\n"
        "Special notes:\n:   Bachelor's degree program students are not eligible\n"
    )
    assert declared_award_levels(text) == []


def test_no_label_means_no_levels():
    assert declared_award_levels("This award is for Master's and PhD students.") == []
