"""Deterministic mock LLM client for pipeline testing."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict

from services.ingestion.extractor import LLMClient


def _relative_date(days: int) -> str:
    """Return an ISO date string offset from today."""
    return (date.today() + timedelta(days=days)).isoformat()


def MOCK_SCHOLARSHIP() -> Dict[str, Any]:
    """Generate mock scholarship data with dates relative to today."""
    return {
        "scholarship_name": "MEXT Scholarship 2027",
        "provider_name": "Ministry of Education, Culture, Sports, Science and Technology",
        "scholarship_type": "Government",
        "country": "Japan",
        "university": None,
        "degree": "Master",
        "funding_type": "Fully Funded",
        "field_of_study": ["Engineering", "Natural Sciences"],
        "application_url": "https://www.studyinjapan.go.jp/en/smap-stopj-applications-scholarships.html",
        "official_source": "https://www.studyinjapan.go.jp/en/",
        "timeline": {
            "application_open": _relative_date(-30),
            "application_deadline": _relative_date(300),
            "interview_date": None,
            "result_date": None,
            "study_start": _relative_date(400),
        },
        "eligibility": {
            "minimum_gpa": 3.5,
            "ielts_required": False,
            "minimum_ielts": None,
            "toefl_required": True,
            "minimum_toefl": 550,
            "gre_required": False,
            "age_limit": 35,
            "work_experience": "Optional",
            "research_experience": "Preferred",
            "publication": "Not Required",
            "recommendation_letter": True,
            "motivation_letter": True,
            "cv_required": True,
            "passport_required": True,
        },
        "benefits": {
            "tuition_fee": True,
            "monthly_allowance": True,
            "accommodation": False,
            "health_insurance": True,
            "travel_ticket": True,
            "research_grant": False,
        },
    }


class MockLLMClient(LLMClient):
    """Returns deterministic scholarship JSON regardless of input."""

    def __init__(self, data: Dict[str, Any] | None = None) -> None:
        self._data = data or MOCK_SCHOLARSHIP()

    def extract_scholarship(self, clean_text: str, source_url: str) -> Dict[str, Any]:
        return self._data
