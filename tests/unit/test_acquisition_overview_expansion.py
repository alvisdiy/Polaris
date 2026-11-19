"""Overview/index pages must expand into their programme children."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.exploration.acquisition_service import AcquisitionService
from services.ingestion.cleaner import AnchorLink, CleanedDocument

PAGE = "https://www.studyinjapan.go.jp/en/planning/scholarships/"


def _cleaned(pairs: list[tuple[str, str]]) -> CleanedDocument:
    return CleanedDocument(
        document_id="doc-1",
        source_id="src-1",
        source_url=PAGE,
        content_type="html",
        clean_text="Scholarships for study in Japan.",
        anchor_links=[AnchorLink(text=text, href=href) for text, href in pairs],
    )


def _service() -> AcquisitionService:
    return AcquisitionService(MagicMock())


class TestProgrammeLinks:
    def test_an_overview_expands_into_its_named_programmes(self):
        cleaned = _cleaned(
            [
                ("Japanese Government (MEXT) Scholarship", f"{PAGE}mext-scholarships/"),
                ("JASSO Scholarship", f"{PAGE}jasso/"),
                ("Scholarships", PAGE),
                ("How to apply", f"{PAGE}apply/"),
                ("Scholarship Guidelines", f"{PAGE}guidelines/"),
                ("Scholarship list", f"{PAGE}list/"),
            ]
        )

        children = _service()._programme_links(cleaned, PAGE)

        assert children == [
            f"{PAGE}mext-scholarships/",
            f"{PAGE}jasso/",
        ]

    def test_a_bare_funding_noun_is_not_a_programme(self):
        cleaned = _cleaned([("Scholarships", f"{PAGE}all/")])
        assert _service()._programme_links(cleaned, PAGE) == []

    def test_a_section_label_is_not_a_programme(self):
        cleaned = _cleaned([("Fellowship Categories", f"{PAGE}categories/")])
        assert _service()._programme_links(cleaned, PAGE) == []

    def test_off_domain_children_are_not_expanded(self):
        cleaned = _cleaned(
            [("MEXT Scholarship", "https://www.mext.go.jp/en/scholarship/")]
        )
        assert _service()._programme_links(cleaned, PAGE) == []

    def test_blocked_hosts_are_not_expanded(self):
        cleaned = _cleaned(
            [("MEXT Scholarship", "https://www.wemakescholars.com/mext")]
        )
        assert _service()._programme_links(cleaned, PAGE) == []

    def test_the_limit_is_honoured(self):
        cleaned = _cleaned(
            [
                (f"Programme {i} Scholarship", f"{PAGE}programme-{i}/")
                for i in range(10)
            ]
        )
        children = _service()._programme_links(cleaned, PAGE, limit=3)
        assert len(children) == 3

    @pytest.mark.parametrize("limit", [1, 2, 4])
    def test_never_more_than_the_configured_child_budget(self, limit):
        cleaned = _cleaned(
            [
                (f"Programme {i} Scholarship", f"{PAGE}programme-{i}/")
                for i in range(10)
            ]
        )
        assert len(_service()._programme_links(cleaned, PAGE, limit=limit)) == limit
