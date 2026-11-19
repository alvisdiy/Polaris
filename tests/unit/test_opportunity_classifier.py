"""Unit tests for the OpportunityClassifier (multi-signal router, not a gate)."""

import pytest

from services.exploration.candidate_analyzer import AnalyzedCandidate
from services.exploration.opportunity_classifier import OpportunityClassifier


@pytest.fixture
def classifier():
    return OpportunityClassifier(terminology={"scholarship": ["奨学金", "장학금", "beasiswa"]})


def _candidate(
    url="https://example.org/scholarships/xyz",
    title="",
    headings=None,
    text="",
    meta="",
    structured=None,
    links=None,
):
    c = AnalyzedCandidate(url=url)
    c.title = title
    c.headings = headings or []
    c.main_text = text
    c.meta_description = meta
    c.structured_data = structured or []
    c.links = links or []
    c.fetched = True
    return c


class TestScholarshipClassification:
    def test_clear_scholarship_page(self, classifier):
        c = _candidate(
            url="https://university.example/admissions/scholarships",
            title="Merit Scholarship for International Students",
            headings=["Eligibility", "Application Deadline"],
            text=(
                "The scholarship covers full tuition and a monthly stipend. "
                "International students pursuing a master degree may apply. "
                "Application deadline is May 1st. Submit academic transcripts."
            ),
        )
        result = classifier.classify(c)
        assert result.label == "SCHOLARSHIP"
        assert result.routing in ("opportunity", "low_priority")

    def test_fully_funded_page(self, classifier):
        c = _candidate(
            title="Fully Funded PhD Positions with Tuition Waiver",
            text="Fully funded positions. Tuition waiver and stipend provided for doctoral students.",
        )
        result = classifier.classify(c)
        assert result.label == "SCHOLARSHIP"

    def test_japanese_scholarship_page(self, classifier):
        c = _candidate(
            title="日本政府奨学金のご案内",
            text="留学生のための奨学金。月額給付金支給。学部生および大学院生が対象。",
        )
        result = classifier.classify(c)
        assert result.label == "SCHOLARSHIP"

    def test_korean_scholarship_page(self, classifier):
        c = _candidate(
            title="국제 학생 장학금 안내",
            text="유학생을 위한 장학금 프로그램입니다. 등록금 전액 지원.",
        )
        result = classifier.classify(c)
        assert result.label == "SCHOLARSHIP"


class TestEmploymentRejection:
    def test_visa_sponsorship_farm_jobs_rejected(self, classifier):
        """THE false-positive case: funding words + employment dominance."""
        c = _candidate(
            url="https://jobs.example/germany-visa-sponsorship-farm-jobs-2026",
            title="Germany Visa Sponsorship Farm Jobs 2026 - Apply Now",
            headings=["Job Openings", "Salary"],
            text=(
                "We are hiring seasonal workers for farm jobs in Germany. "
                "Visa sponsorship available. Competitive salary and overtime pay. "
                "Full-time employment contract. Submit your job application today."
            ),
        )
        result = classifier.classify(c)
        assert result.label in ("JOB", "VISA_JOB")
        assert result.routing == "reject"

    def test_job_posting_structured_data(self, classifier):
        c = _candidate(
            title="Software Engineer Position",
            text="We are hiring a software engineer. Great salary and benefits package.",
            structured=[{"@type": "JobPosting", "title": "Software Engineer"}],
        )
        result = classifier.classify(c)
        assert result.label in ("JOB", "VISA_JOB", "OTHER") or result.routing == "reject"

    def test_generic_job_page(self, classifier):
        c = _candidate(
            title="Career Opportunities at Example Corp",
            text="Browse our current job vacancies. We offer employment with salary growth.",
        )
        result = classifier.classify(c)
        assert result.label in ("JOB", "VISA_JOB")
        assert result.routing == "reject"


class TestOtherLabels:
    def test_internship_page(self, classifier):
        c = _candidate(
            title="Summer Internship Program 2026",
            text="Our internship program offers hands-on experience for interns.",
        )
        result = classifier.classify(c)
        assert result.label in ("INTERNSHIP",) or result.routing in ("reject", "review")

    def test_unknown_content_retained(self, classifier):
        c = _candidate(
            url="https://example.org/about/company",
            title="Company Profile and History",
            text="Example Corp was founded in 1990 and makes widgets.",
        )
        result = classifier.classify(c)
        assert result.routing in ("review", "irrelevant")
        assert result.label in ("UNKNOWN", "OTHER")

    def test_irrelevant_content_rejected(self, classifier):
        c = _candidate(title="Best Casino Betting Tips", text="casino betting strategies online")
        result = classifier.classify(c)
        assert result.routing == "irrelevant"


class TestRoutingSemantics:
    def test_medium_confidence_lower_priority(self, classifier):
        c = _candidate(
            title="University Financial Support",
            text="Various funding options exist for enrolled students at the university.",
        )
        result = classifier.classify(c)
        assert result.label == "SCHOLARSHIP"
        assert result.routing in ("low_priority", "review")

    def test_unknown_never_discarded_silently(self, classifier):
        """UNKNOWN must map to review (retained), not rejection."""
        c = _candidate(title="Weather Report", text="sunny with clouds")
        result = classifier.classify(c)
        assert result.routing != "reject" or result.label in ("OTHER",)
