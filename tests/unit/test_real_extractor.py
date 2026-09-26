"""Tests for DeterministicLLMClient.extract_scholarship()."""

import pytest
from services.ingestion.real_extractor import DeterministicLLMClient

@pytest.fixture
def client():
    return DeterministicLLMClient()


def test_title_extraction(client):
    text = "# Amazing Scholarship for Engineers\nSome description"
    result = client._extract_title(text)
    assert result == "Amazing Scholarship for Engineers"

@pytest.mark.parametrize(
    "date_str,expected",
    [
        ("deadline: May 15, 2024", "2024-05-15"),
        ("application deadline: 2024-06-01", "2024-06-01"),
        ("Apply by: 01.07.2024", "2024-07-01"),
        ("deadline 15 May 2024", "2024-05-15"),
        ("deadline: 2024/08/20", "2024-08-20"),
    ],
)
def test_deadline_formats(client, date_str, expected):
    text = f"{date_str}\nOther info"
    deadline = client._extract_deadline(text)
    assert deadline == expected

def test_full_extraction(client):
    clean_text = """# Global Tech Scholarship

deadline: September 30, 2024

GPA: 3.5
Age limit: 25
TOEFL: 100

Benefits:
- tuition
- accommodation
"""
    source_url = "https://example.com/scholarship"
    data = client.extract_scholarship(clean_text, source_url)
    assert data["scholarship_name"] == "Global Tech Scholarship"
    assert data["timeline"]["application_deadline"] == "2024-09-30"
    assert data["eligibility"]["minimum_gpa"] == 3.5
    assert data["eligibility"]["age_limit"] == 25
    assert data["eligibility"]["toefl_required"] is True
    assert data["eligibility"]["minimum_toefl"] == 100
    assert data["benefits"]["tuition_fee"] is True
    assert data["benefits"]["accommodation"] is True
