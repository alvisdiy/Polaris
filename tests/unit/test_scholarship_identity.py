"""Canonical identity: what counts as the same scholarship.

Every case here is paired with a case that must *not* collapse. A canonicaliser
that only ever merges is indistinguishable from one that works.
"""

from __future__ import annotations

import pytest

from services.scholarship.identity import (
    IdentityUnavailable,
    canonical_scholarship_name,
    canonical_url,
    detect_cross_country_clones,
    scholarship_identity_key,
)

pytestmark = pytest.mark.unit

PROVIDER = "11111111-1111-1111-1111-111111111111"
COUNTRY = "22222222-2222-2222-2222-222222222222"
OTHER_PROVIDER = "33333333-3333-3333-3333-333333333333"
OTHER_COUNTRY = "44444444-4444-4444-4444-444444444444"


# --- formatting variants of one scholarship -------------------------------

FORMATTING_VARIANTS = [
    "Global Excellence Scholarship",
    "Global  Excellence Scholarship",
    "GLOBAL EXCELLENCE SCHOLARSHIP",
    "  Global Excellence Scholarship!  ",
    "Global Excellence Scholarship ",
]

# --- shapes seen on the live corpus ----------------------------------------

GLOUED_HEADING_VARIANTS = [
    ("Opportunity Scholarship\nScholarship", "Opportunity Scholarship"),
    (
        "Scholarship for Foreign Students\nScholarship",
        "Scholarship for Foreign Students",
    ),
    (
        "International Excellence Scholarships\nScholarship",
        "International Excellence Scholarships",
    ),
    (
        "Loughborough University Sanctuary Scholarships\nSanctuary Scholarship",
        "Loughborough University Sanctuary Scholarships",
    ),
    (
        "SP Scholarship and SP Engineering Scholarship\n"
        "The SP Scholarship and SP Engineering Scholarship",
        "SP Scholarship & SP Engineering Scholarship",
    ),
]


@pytest.mark.parametrize("name", FORMATTING_VARIANTS)
def test_formatting_variants_share_one_canonical_form(name):
    assert canonical_scholarship_name(name) == "global excellence scholarship"


@pytest.mark.parametrize("glued,plain", GLOUED_HEADING_VARIANTS)
def test_a_name_glued_to_its_own_heading_collapses(glued, plain):
    """A page that concatenates <h1> and <title> is still one scholarship."""
    assert canonical_scholarship_name(glued) == canonical_scholarship_name(plain)


def test_definite_article_does_not_change_the_name():
    assert canonical_scholarship_name("The SP Undergraduate Scholarship") == (
        canonical_scholarship_name("SP Undergraduate Scholarship")
    )


def test_plural_funding_noun_singularises():
    assert canonical_scholarship_name("Sport Scholarships") == (
        canonical_scholarship_name("Sport Scholarship")
    )


# --- must stay distinct ----------------------------------------------------

DISTINCT_PAIRS = [
    # A different programme, not a spelling variant.
    ("Global Excellence Scholarship", "Global Excellence Research Scholarship"),
    # Different application cycles of one programme.
    ("Fulbright Scholarship 2026", "Fulbright Scholarship 2027"),
    # Brackets carry meaning.
    ("MEXT Scholarship (Research Students)", "MEXT Scholarship Research Students"),
    # Two awards documented on one page (LPDP, DAAD).
    ("LPDP Beasiswa Reguler (Master)", "LPDP Beasiswa Reguler (PhD)"),
    ("DAAD Research Grants - Doctoral Programmes in Germany", "DAAD Research Grants - Short-Term Grants"),
    # An indefinite article is the difference between two awards.
    ("A Star Scholarship", "Star Scholarship"),
    ("Chevening Scholarships", "Chevening SIDS Scholarship"),
    ("Japanese Government (Monbukagakusho: MEXT) Scholarships", "Pamphlet Scholarship"),
    # A trailing line that adds new content is a new name.
    (
        "Requirements to apply Applicants information\nGeneral Scholarship",
        "Requirements to apply Applicants information",
    ),
]


@pytest.mark.parametrize("left,right", DISTINCT_PAIRS)
def test_genuinely_distinct_scholarships_do_not_collapse(left, right):
    assert canonical_scholarship_name(left) != canonical_scholarship_name(right)


def test_a_year_in_the_name_is_preserved():
    assert canonical_scholarship_name("Scholarship 2026").endswith("2026")


def test_balanced_brackets_survive_canonicalisation():
    assert canonical_scholarship_name("MEXT Scholarship (Research Students)") == (
        "mext scholarship (research students)"
    )


def test_empty_name_canonicalises_to_empty():
    assert canonical_scholarship_name("   ") == ""


# --- identity key ----------------------------------------------------------


def test_identity_is_stable_across_formatting():
    spellings = (
        "Global Excellence Scholarship",
        "GLOBAL  EXCELLENCE SCHOLARSHIP!",
        " Global Excellence Scholarship ",
    )
    keys = {scholarship_identity_key(PROVIDER, name, COUNTRY) for name in spellings}
    assert len(keys) == 1


def test_identity_separates_different_providers():
    assert scholarship_identity_key(PROVIDER, "Eiffel Scholarship", COUNTRY) != (
        scholarship_identity_key(OTHER_PROVIDER, "Eiffel Scholarship", COUNTRY)
    )


def test_identity_separates_different_countries():
    assert scholarship_identity_key(PROVIDER, "Eiffel Scholarship", COUNTRY) != (
        scholarship_identity_key(PROVIDER, "Eiffel Scholarship", OTHER_COUNTRY)
    )


def test_identity_separates_different_application_cycles():
    assert scholarship_identity_key(PROVIDER, "Eiffel Scholarship 2026", COUNTRY) != (
        scholarship_identity_key(PROVIDER, "Eiffel Scholarship 2027", COUNTRY)
    )


def test_identity_key_is_a_sha256_hex_digest():
    key = scholarship_identity_key(PROVIDER, "Eiffel Scholarship", COUNTRY)
    assert len(key) == 64 and all(c in "0123456789abcdef" for c in key)


@pytest.mark.parametrize(
    "provider,country,name",
    [
        (None, COUNTRY, "Eiffel Scholarship"),
        (PROVIDER, None, "Eiffel Scholarship"),
        (PROVIDER, COUNTRY, "   "),
    ],
)
def test_identity_refuses_to_be_derived_from_missing_data(provider, country, name):
    """A hash of empty strings would collide with every other incomplete row."""
    with pytest.raises(IdentityUnavailable):
        scholarship_identity_key(provider, name, country)


# --- URL canonicalisation --------------------------------------------------


def test_url_ignores_host_case_fragment_and_tracking_params():
    assert canonical_url("https://StudyinJapan.go.jp/en/x/?utm_source=g#top") == (
        canonical_url("https://studyinjapan.go.jp/en/x")
    )


def test_url_preserves_scheme():
    """http and https may serve different content; folding them is a guess."""
    assert canonical_url("https://ex.com/p") != canonical_url("http://ex.com/p")


def test_url_preserves_meaningful_query_parameters():
    assert canonical_url("https://ex.com/p?id=3") != canonical_url("https://ex.com/p?id=4")


def test_url_ignores_parameter_order():
    assert canonical_url("https://ex.com/p?b=2&a=1") == canonical_url("https://ex.com/p?a=1&b=2")


def test_url_normalises_trailing_slash_and_duplicate_separators():
    assert canonical_url("https://ex.com/a//b/") == canonical_url("https://ex.com/a/b")


def test_blank_url_canonicalises_to_none():
    assert canonical_url(None) is None
    assert canonical_url("") is None


# --- cross-country clone reporting ----------------------------------------


def test_cross_country_clone_detector_reports_the_split():
    """A scholarship split by discovery scope must be visible, not merged.

    ``country_id`` can be inherited from the source rather than stated by the
    page, so one international scholarship discovered from two country runs
    becomes two rows. Which one is real is not provable from the data, so the
    detector reports instead of merging.
    """

    class Row:
        def __init__(self, provider, name, country):
            self.provider_id = provider
            self.scholarship_name = name
            self.country_id = country

    class Session:
        def __init__(self, rows):
            self._rows = rows

        def query(self, *_columns):
            return iter(self._rows)

    rows = [
        Row(PROVIDER, "Chevening Scholarship", COUNTRY),
        Row(PROVIDER, "chevening  scholarship", OTHER_COUNTRY),
        Row(PROVIDER, "Eiffel Scholarship", COUNTRY),
    ]

    clones = detect_cross_country_clones(Session(rows))

    assert len(clones) == 1
    canonical_name, provider_id, country_a, country_b = clones[0]
    assert canonical_name == "chevening scholarship"
    assert provider_id == PROVIDER
    assert {country_a, country_b} == {COUNTRY, OTHER_COUNTRY}


def test_cross_country_clone_detector_is_quiet_when_nothing_is_split():
    class Row:
        def __init__(self, provider, name, country):
            self.provider_id = provider
            self.scholarship_name = name
            self.country_id = country

    class Session:
        def __init__(self, rows):
            self._rows = rows

        def query(self, *_columns):
            return iter(self._rows)

    rows = [
        Row(PROVIDER, "Chevening Scholarship", COUNTRY),
        Row(PROVIDER, "Eiffel Scholarship", OTHER_COUNTRY),
    ]
    assert detect_cross_country_clones(Session(rows)) == []
