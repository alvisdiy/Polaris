"""Real false positives from the live runs must not be DETAIL pages."""

from __future__ import annotations

import pytest

from services.exploration.acquisition_policy import PageType, classify_page
from services.exploration.page_intent import PageIntent, classify_page_intent


def classify(url: str, title: str, *, headings=None, anchors=None, text=""):
    return classify_page_intent(
        url=url,
        page_title=title,
        headings=headings or [title],
        anchors=anchors or [],
        text=text,
    )


class TestCollectionPagesAreNotDetails:
    def test_a_topics_news_post_is_not_a_scholarship(self):
        result = classify(
            "https://www.jsps.go.jp/english/e-topics/2026/0821.html",
            "JSPS Topics",
            anchors=["Fellowship program", "Grant"],
            text="Latest topics from JSPS. Fellowship applications are announced here.",
        )
        assert result.intent != PageIntent.SCHOLARSHIP_DETAIL

    def test_fellowship_categories_is_not_one_fellowship(self):
        result = classify(
            "https://ny.jpf.go.jp/grants/grants-for-japanese-studies/fellowship-program/",
            "2027-2028 Fellowship Categories",
            anchors=["Research Fellowship", "Doctoral Fellowship", "Master's Fellowship"],
            text="The program offers several fellowship categories. See each category for details.",
        )
        assert result.intent != PageIntent.SCHOLARSHIP_DETAIL

    def test_fees_and_funding_is_not_a_programme(self):
        result = classify(
            "https://www.example.ac.uk/study/fees-and-funding/",
            "Fees and funding",
            anchors=["Scholarships", "Bursaries"],
            text="Tuition fees and funding options for students.",
        )
        assert result.intent != PageIntent.SCHOLARSHIP_DETAIL

    def test_a_numbered_section_is_not_a_programme(self):
        result = classify(
            "https://www.example.ac.uk/scholarship-application-process/",
            "3. Interview",
            anchors=["Scholarships"],
            text="The interview stage follows the written application.",
        )
        assert result.intent != PageIntent.SCHOLARSHIP_DETAIL


class TestRealDetailsSurvive:
    def test_a_programme_with_deadline_and_eligibility_is_a_detail(self):
        result = classify(
            "https://ny.jpf.go.jp/grants/grants-for-japanese-studies/fellowship-program/",
            "Japanese Studies Fellowship Program",
            text=(
                "Application deadline: 31 January 2027. "
                "Eligibility: applicants must hold a PhD. "
                "Benefits: monthly stipend and travel costs. "
                "How to apply: submit the application form."
            ),
        )
        assert result.intent == PageIntent.SCHOLARSHIP_DETAIL


class TestAggregatorsAreNeverOfficial:
    def test_an_aggregator_url_is_classified_as_an_aggregator(self):
        assessment = classify_page(
            "https://www.wemakescholars.com/bachelors-scholarships-for-international-students"
        )
        assert assessment.page_type == PageType.AGGREGATOR
        assert not assessment.is_scholarship_page
        assert not assessment.should_discover_links

    @pytest.mark.parametrize(
        "url",
        [
            "https://scholarshipbob.com/scholarships-by-organisation/unesco",
            "https://www.opportunitiesforyouth.org/2026/01/fully-funded-scholarship/",
            "https://www.prospects.ac.uk/postgraduate-recruiters",
        ],
    )
    def test_other_aggregators_are_classified_the_same_way(self, url):
        assert classify_page(url).page_type == PageType.AGGREGATOR
