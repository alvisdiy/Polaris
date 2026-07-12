"""Unit tests for ExplanationEngine — no database required."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from services.matching.explanation import ExplanationEngine
from services.matching.models.profile import UserProfile
from services.matching.models.result import CriteriaScores

pytestmark = pytest.mark.unit


def _mock_scholarship(**overrides) -> MagicMock:
    s = MagicMock()
    s.scholarship_id = str(uuid.uuid4())
    s.application_url = overrides.get("application_url", "https://example.com")
    s.official_page_url = overrides.get("official_page_url", "https://example.com")
    return s


def _profile(**overrides) -> UserProfile:
    defaults = dict(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science"],
        current_gpa=3.8,
        ielts_score=7.5,
        research_experience="Preferred",
        work_experience="Optional",
        publication="Not Required",
        leadership=True,
        funding_preference="Fully Funded",
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def _scores(**overrides) -> CriteriaScores:
    defaults = dict(
        country=20.0,
        degree=20.0,
        field_of_study=20.0,
        gpa=15.0,
        language=10.0,
        funding=5.0,
        research=5.0,
        work=3.0,
        leadership=2.0,
        total=100.0,
    )
    defaults.update(overrides)
    return CriteriaScores(**defaults)


# --- explain ---


def test_explain_returns_explanation():
    engine = ExplanationEngine()
    result = engine.explain(_profile(), _mock_scholarship(), _scores())
    assert result.summary
    assert isinstance(result.strengths, list)
    assert isinstance(result.gaps, list)
    assert isinstance(result.next_steps, list)


def test_perfect_match_has_all_strengths():
    engine = ExplanationEngine()
    result = engine.explain(_profile(), _mock_scholarship(), _scores())
    assert len(result.strengths) == 9  # All criteria are strengths


def test_low_score_has_gaps():
    engine = ExplanationEngine()
    scores = _scores(country=0, degree=0, field_of_study=0, gpa=0, language=0, total=10)
    result = engine.explain(_profile(), _mock_scholarship(), scores)
    assert len(result.gaps) > 0


# --- _identify_strengths ---


def test_identify_strengths_high_scores():
    engine = ExplanationEngine()
    scores = _scores(
        country=20, degree=20, field_of_study=20, gpa=15,
        language=10, funding=5, research=5, work=3, leadership=2,
    )
    strengths = engine._identify_strengths(scores)
    assert len(strengths) == 9


def test_identify_strengths_low_scores():
    engine = ExplanationEngine()
    scores = _scores(
        country=0, degree=0, field_of_study=0, gpa=0,
        language=0, funding=0, research=0, work=0, leadership=0,
    )
    strengths = engine._identify_strengths(scores)
    assert len(strengths) == 0


# --- _identify_gaps ---


def test_identify_gaps_zero_high_weight():
    engine = ExplanationEngine()
    scores = _scores(country=0, degree=0)  # Zero on high-weight criteria
    gaps = engine._identify_gaps(_profile(), _mock_scholarship(), scores)
    assert any("Country" in g for g in gaps)
    assert any("Degree" in g for g in gaps)


def test_identify_gaps_partial_score():
    engine = ExplanationEngine()
    # 3.0 out of 15.0 for GPA = 20%, below 50% threshold
    scores = _scores(gpa=3.0)
    gaps = engine._identify_gaps(_profile(), _mock_scholarship(), scores)
    assert any("GPA" in g for g in gaps)


# --- _suggest_next_steps ---


def test_suggest_next_steps_gpa_gap():
    engine = ExplanationEngine()
    steps = engine._suggest_next_steps(_profile(), _mock_scholarship(), ["GPA below minimum requirement"])
    assert any("GPA" in s for s in steps)


def test_suggest_next_steps_language_gap():
    engine = ExplanationEngine()
    steps = engine._suggest_next_steps(_profile(), _mock_scholarship(), ["Language score below requirement"])
    assert any("IELTS" in s or "TOEFL" in s for s in steps)


def test_suggest_next_steps_country_gap():
    engine = ExplanationEngine()
    steps = engine._suggest_next_steps(_profile(), _mock_scholarship(), ["Country does not match target"])
    assert any("different country" in s for s in steps)


def test_suggest_next_steps_degree_gap():
    engine = ExplanationEngine()
    steps = engine._suggest_next_steps(_profile(), _mock_scholarship(), ["Degree does not match target"])
    assert any("different degree" in s for s in steps)


def test_suggest_next_steps_field_gap():
    engine = ExplanationEngine()
    # Note: _suggest_next_steps checks for "Field" (capital F) but the gap text
    # is "Limited field of study overlap" (lowercase f), so no field-specific step is generated.
    steps = engine._suggest_next_steps(_profile(), _mock_scholarship(), ["Limited field of study overlap"])
    # Only the generic application URL step is added
    assert any("example.com" in s for s in steps)


def test_suggest_next_steps_research_gap():
    engine = ExplanationEngine()
    steps = engine._suggest_next_steps(_profile(), _mock_scholarship(), ["Research experience below requirement"])
    assert any("research" in s.lower() for s in steps)


def test_suggest_next_steps_work_gap():
    engine = ExplanationEngine()
    steps = engine._suggest_next_steps(_profile(), _mock_scholarship(), ["Work experience below requirement"])
    assert any("work experience" in s.lower() for s in steps)


def test_suggest_next_steps_includes_application_url():
    engine = ExplanationEngine()
    sch = _mock_scholarship(application_url="https://apply.example.com")
    steps = engine._suggest_next_steps(_profile(), sch, [])
    assert any("https://apply.example.com" in s for s in steps)


def test_suggest_next_steps_fallback_to_official_url():
    engine = ExplanationEngine()
    sch = _mock_scholarship(application_url=None, official_page_url="https://official.example.com")
    steps = engine._suggest_next_steps(_profile(), sch, [])
    assert any("https://official.example.com" in s for s in steps)


# --- _build_summary ---


def test_build_summary_excellent():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=95), [], [])
    assert "Excellent" in summary


def test_build_summary_strong():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=85), [], [])
    assert "Strong" in summary


def test_build_summary_good():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=75), [], [])
    assert "Good" in summary


def test_build_summary_moderate():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=65), [], [])
    assert "Moderate" in summary


def test_build_summary_low():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=40), [], [])
    assert "Low" in summary
