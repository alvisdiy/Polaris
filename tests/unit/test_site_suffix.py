"""Site suffixes are publisher names, never part of the award."""

from __future__ import annotations

import pytest

from services.ingestion.extraction_quality import strip_site_suffix


class TestAsciiSeparators:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("PFP Study Award | Temasek Polytechnic", "PFP Study Award"),
            ("DAAD Scholarships - An Overview - DAAD", "DAAD Scholarships - An Overview"),
            ("Chevening Scholarships · Chevening", "Chevening Scholarships"),
        ],
    )
    def test_known_separators_are_stripped(self, title, expected):
        assert strip_site_suffix(title) == expected


class TestFullWidthSeparator:
    def test_full_width_bar_is_stripped(self):
        # Observed on studyinjapan.go.jp detail pages: the publisher appends its
        # name after U+FF5C, which the ASCII-only separator list missed.
        assert (
            strip_site_suffix("Tuition reduction system｜Study in Japan Official Website")
            == "Tuition reduction system"
        )

    def test_the_published_name_no_longer_contains_the_publisher(self):
        name = strip_site_suffix("Tuition Exemption｜Study in Japan Official Website")
        assert name == "Tuition Exemption"
        assert "Study in Japan" not in name
