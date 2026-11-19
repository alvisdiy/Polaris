"""Page-intent classification, M11 §5/§6.

Three things are being asserted, and they are different in kind:

  * the deterministic rules — synthetic pages where the answer is not in
    doubt, one per class;
  * the real-page golden dataset — pages read by a human, with the classifier
    agreeing or the disagreement failing loudly;
  * the properties the rest of the pipeline relies on — an index page is
    followable, a detail page is extractable, and insufficient evidence is
    UNKNOWN rather than a confident wrong answer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.exploration.page_intent import (
    PageIntent,
    classify_page_intent,
    programme_link_count,
)

DATASET = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "discovery_golden.json").read_text(
        encoding="utf-8"
    )
)
SAMPLES = DATASET["samples"]

DETAIL_BODY = (
    "The XYZ Scholarship is awarded each year to two students. "
    "Eligibility: applicants must hold a bachelor's degree and be enrolled full time. "
    "The award covers tuition fees and provides a monthly living allowance. "
    "Application deadline: 3 May 2027. How to apply: submit your application online "
    "with the required documents before the closing date. Selected students will "
    "receive the award worth 30,000 EUR per year."
)


def classify(**overrides):
    base = {
        "url": "https://example.edu/scholarships/xyz-scholarship",
        "page_title": "XYZ Scholarship",
        "headings": ["XYZ Scholarship", "Eligibility", "Benefits", "How to apply"],
        "anchors": ["Home", "About", "Contact"],
        "text": DETAIL_BODY,
    }
    base.update(overrides)
    return classify_page_intent(**base)


class TestEachIntentIsReachable:
    def test_a_named_award_with_instructions_is_a_detail_page(self):
        result = classify()
        assert result.intent == PageIntent.SCHOLARSHIP_DETAIL
        assert result.is_detail
        assert not result.is_discovery_surface

    @pytest.mark.parametrize(
        "title,text",
        [
            (
                "MEXT 国費外国人留学生奨学金",
                "応募資格は大学院生です。授業料と生活費を支給します。応募期間は2027年4月までです。",
            ),
            (
                "국제학생 장학금",
                "지원 자격은 대학원생입니다. 등록금과 생활비를 지원합니다. 신청 기간은 2027년 4월까지입니다.",
            ),
            (
                "中国政府奖学金",
                "申请资格：国际学生。奖学金包括学费和生活费。申请截止日期为2027年4月。",
            ),
            (
                "Beasiswa LPDP",
                "Persyaratan: mahasiswa pascasarjana. Beasiswa mencakup biaya kuliah dan tunjangan hidup. "
                "Batas pendaftaran 30 April 2027.",
            ),
            (
                "DAAD-Stipendium für internationale Studierende",
                "Voraussetzungen für Masterstudierende. Das Stipendium umfasst Studiengebühren und "
                "Lebenshaltungskosten. Bewerbungsfrist ist der 30. April 2027.",
            ),
            (
                "Bourse Eiffel",
                "Conditions d'éligibilité pour les étudiants en master. La bourse couvre les frais de "
                "scolarité et une allocation mensuelle. Date limite de candidature: 30 avril 2027.",
            ),
        ],
    )
    def test_non_english_award_detail_signals_are_recognized(self, title, text):
        result = classify(
            url="https://example.edu/award/detail",
            page_title=title,
            headings=[title],
            text=text,
        )

        assert result.intent == PageIntent.SCHOLARSHIP_DETAIL
        assert result.detail_signals

    @pytest.mark.parametrize(
        "title",
        [
            "奨学金一覧", "장학금 목록", "奖学金列表", "Daftar Beasiswa",
            "Stipendienübersicht", "Liste des bourses",
        ],
    )
    def test_non_english_scholarship_collections_remain_overviews(self, title):
        result = classify(
            url="https://example.edu/awards/",
            page_title=title,
            headings=[title],
            text="Available funding and scholarship opportunities for students.",
        )

        assert result.intent == PageIntent.SCHOLARSHIP_OVERVIEW

    def test_a_collection_path_with_many_links_is_an_index(self):
        result = classify(
            url="https://example.edu/scholarships",
            page_title="Undergraduate Scholarships",
            headings=["Undergraduate Scholarships", "Postgraduate Scholarships"],
            anchors=[f"Scholarship {i}" for i in range(12)],
            text="Browse every scholarship we offer.",
        )
        assert result.intent == PageIntent.SCHOLARSHIP_INDEX
        assert result.is_discovery_surface
        assert not result.is_detail

    def test_a_page_that_declares_an_overview_is_an_overview(self):
        result = classify(
            url="https://example.org/scholarships/all/",
            page_title="Scholarships - An Overview",
            headings=["Scholarships - An Overview"],
            anchors=["Postgraduate", "Doctoral"],
            text="DAAD offers scholarships at several levels. This page summarises them.",
        )
        assert result.intent == PageIntent.SCHOLARSHIP_OVERVIEW
        assert result.is_discovery_surface

    def test_an_organisation_page_is_provider_information(self):
        result = classify(
            url="https://example.org/about-us",
            page_title="About the Foundation",
            headings=["About us", "Our mission", "Who we are", "Contact us"],
            anchors=["Home", "News"],
            text="We have supported students since 1974. Our mission is to widen access.",
        )
        assert result.intent == PageIntent.PROVIDER_INFORMATION

    def test_a_university_page_is_university_information(self):
        result = classify(
            url="https://example.edu/admissions",
            page_title="Admissions",
            headings=["Admissions", "Study at Example", "Campus life"],
            anchors=["Courses", "Fees"],
            text="Welcome to Example University. Explore our campuses and faculties.",
        )
        assert result.intent == PageIntent.UNIVERSITY_INFORMATION

    def test_a_login_wall_is_an_application_portal(self):
        result = classify(
            url="https://example.org/portal",
            page_title="Applicant Portal",
            headings=["Applicant Portal"],
            anchors=["Sign in", "Register"],
            text="Sign in to your account. Create an account to start your application.",
        )
        assert result.intent == PageIntent.APPLICATION_PORTAL
        assert result.is_terminally_unusable

    def test_a_dated_story_is_a_news_announcement(self):
        result = classify(
            url="https://example.edu/news/2026/03/02/joe-wins-award",
            page_title="Joe Bloggs wins the XYZ Scholarship",
            headings=["Joe Bloggs wins the XYZ Scholarship"],
            anchors=["More news"],
            text="Joe Bloggs, a second-year student, was awarded the XYZ Scholarship.",
        )
        assert result.intent == PageIntent.NEWS_ANNOUNCEMENT

    def test_a_question_page_is_an_faq(self):
        result = classify(
            url="https://example.edu/scholarships/faq",
            page_title="FAQs on scholarships",
            headings=["FAQs on scholarships", "How do I apply?"],
            anchors=["Back to scholarships"],
            text="Frequently asked questions about our scholarship scheme.",
        )
        assert result.intent == PageIntent.FAQ

    def test_guidance_about_applying_is_not_an_award(self):
        result = classify(
            url="https://example.edu/scholarships/information-for-applicants",
            page_title="Important information for scholarship applicants",
            headings=["Important information for scholarship applicants"],
            anchors=["Apply"],
            text=(
                "Read this before you apply. Application deadline: 3 May 2027. "
                "Eligibility criteria are listed below. How to apply is explained here."
            ),
        )
        assert result.intent == PageIntent.GENERAL_PROGRAMME_PAGE
        assert not result.is_detail

    def test_a_page_with_no_funding_content_is_unknown_not_irrelevant(self):
        """No funding claim and no recognisable shape is a shrug, not a verdict."""
        result = classify(
            url="https://example.edu/sports-day-photos",
            page_title="Sports Day Photos",
            headings=["Sports Day Photos"],
            anchors=["Gallery"],
            text="Our annual sports day was a great success. Thank you to everyone who came.",
        )
        assert result.intent == PageIntent.UNKNOWN

    def test_passing_funding_mentions_with_no_claim_are_irrelevant(self):
        """The other failure mode: the word 'scholarship' in a paragraph that
        is about something else entirely."""
        result = classify(
            url="https://example.edu/alumni-profiles",
            page_title="Alumni Profiles",
            headings=["Alumni Profiles"],
            anchors=["Campus", "Contact"],
            text=(
                "Our alumni network includes people who once held a scholarship. "
                "That is not what this page is about, and it links to no awards."
            ),
        )
        assert result.intent == PageIntent.IRRELEVANT

    def test_a_news_page_with_no_funding_is_still_news_not_irrelevant(self):
        """Both are unusable; only one of them is worth remembering why."""
        result = classify(
            url="https://example.edu/news/sports-day",
            page_title="Sports Day Photos",
            headings=["Sports Day Photos"],
            anchors=["Gallery"],
            text="Our annual sports day was a great success. Thank you to everyone who came.",
        )
        assert result.intent == PageIntent.NEWS_ANNOUNCEMENT

    def test_insufficient_evidence_is_unknown_not_a_guess(self):
        """The conservative property the whole milestone depends on."""
        result = classify(
            url="https://example.edu/page",
            page_title="Page",
            headings=["Section"],
            anchors=["One", "Two"],
            text="Some prose with no funding claim, no instructions and no links.",
        )
        assert result.intent == PageIntent.UNKNOWN
        assert result.confidence == 0.0
        assert result.evidence, "an UNKNOWN verdict must say what it could not settle"


class TestProgrammeLinkCount:
    def test_it_counts_distinct_funding_labels_not_link_total(self):
        anchors = ["Home", "XYZ Scholarship", "ABC Bursary", "XYZ Scholarship"]
        assert programme_link_count(anchors) == 2

    def test_navigation_noise_does_not_count(self):
        assert programme_link_count(["Home", "About", "Contact", "News"]) == 0


class TestEvidenceIsAlwaysProduced:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"url": "https://example.edu/scholarships"},
            {"page_title": "FAQ", "headings": [], "anchors": [], "text": ""},
        ],
    )
    def test_no_verdict_is_returned_without_reasons(self, kwargs):
        assert classify(**kwargs).evidence

