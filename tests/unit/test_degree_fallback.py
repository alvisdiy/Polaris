"""Degree inference from evidence the page carries, not from prose it may not."""

from __future__ import annotations

import pytest

from services.domain.degree_fallback import infer_degree, infer_degree_levels


@pytest.mark.parametrize(
    "name,url,expected",
    [
        ("PhD Studentship in Control Engineering", "https://x.edu/award", "PhD"),
        ("SOAS Master's Scholarships (International) 2026", "https://soas.ac.uk/x", "Master"),
        ("MBA Progress with Purpose Scholarship", "https://lboro.ac.uk/x", "Master"),
        ("2026 Global Korea Scholarship program for Undergraduate Degrees", "https://x.kr/y", "Bachelor"),
        ("Erasmus+ Exchange Programme", "https://x.nl/z", "Exchange"),
        ("Alumni Bursary", "https://lboro.ac.uk/study/postgraduate/fees-funding/masters-funding/alumni/", "Master"),
        ("Alumni Bursary", "https://lboro.ac.uk/donate/", None),
    ],
)
def test_one_signal_names_the_level(name, url, expected):
    assert infer_degree(name, url) == expected


def test_two_disagreeing_signals_are_left_unknown():
    """"PhD Scholarship" under /masters/ is a contradiction, not a value."""
    assert infer_degree("PhD Scholarship", "https://x.edu/masters/phd-scholarship") is None


def test_postgraduate_alone_is_not_mapped():
    """"Postgraduate" covers Master's and PhD in British usage."""
    assert infer_degree("Postgraduate Scholarship", "https://x.edu/study/postgraduate/") is None


def test_a_name_naming_several_levels_returns_a_set():
    assert set(infer_degree_levels("PhD and Master's Scholarships 2027", "https://x.edu/a")) == {
        "Master",
        "PhD",
    }


def test_a_single_level_name_is_not_a_set():
    assert infer_degree_levels("Master's Scholarship", "https://x.edu/a") == []
