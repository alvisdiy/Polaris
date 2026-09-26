"""Unit tests for ExplanationEngine — no database required."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from services.matching.explanation import ExplanationEngine
from services.matching.models.profile import UserProfile
from services.matching.models.result import CriteriaScores, CriterionResult

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


def _detail(criterion: str, score: float, weight: float, matched: bool, reason: str) -> CriterionResult:
    return CriterionResult(criterion=criterion, score=score, weight=weight, matched=matched, reason=reason)


def _perfect_details() -> list[CriterionResult]:
    """All criteria matched — perfect score."""
    return [
        _detail("country", 20, 20, True, "Country 'Japan' matches target."),
        _detail("degree", 20, 20, True, "Degree 'Master' matches."),
        _detail("field_of_study", 20, 20, True, "Field overlap 1/1."),
        _detail("gpa", 15, 15, True, "GPA 3.8 vs minimum 3.0."),
        _detail("language", 10, 10, True, "IELTS 7.5 vs minimum 6.5."),
        _detail("funding", 5, 5, True, "Funding type matches."),
        _detail("research", 5, 5, True, "Research meets requirement."),
        _detail("work", 3, 3, True, "Work meets requirement."),
        _detail("leadership", 2, 2, True, "User has leadership."),
    ]


def _gap_details() -> list[CriterionResult]:
    """Most criteria are gaps."""
    return [
        _detail("country", 0, 20, False, "Country 'Germany' does not match 'Japan'."),
        _detail("degree", 0, 20, False, "Requires 'PhD', user has 'Master'."),
        _detail("field_of_study", 0, 20, False, "No field overlap."),
        _detail("gpa", 10, 15, False, "GPA 3.0 vs minimum 3.5."),
        _detail("language", 0, 10, False, "IELTS required but user has no score."),
        _detail("funding", 0, 5, False, "Funding mismatch."),
        _detail("research", 0, 5, False, "Research well below requirement."),
        _detail("work", 0, 3, False, "Work well below requirement."),
        _detail("leadership", 0, 2, False, "No leadership experience."),
    ]


def _scores(details: list[CriterionResult] | None = None, **overrides) -> CriteriaScores:
    dets = details or _perfect_details()
    defaults = dict(
        country=20.0, degree=20.0, field_of_study=20.0, gpa=15.0,
        language=10.0, funding=5.0, research=5.0, work=3.0, leadership=2.0,
        total=100.0, details=dets,
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
    assert len(result.gaps) == 0


def test_low_score_has_gaps():
    engine = ExplanationEngine()
    details = _gap_details()
    scores = _scores(details=details, country=0, degree=0, field_of_study=0,
                     gpa=10, language=0, funding=0, research=0, work=0,
                     leadership=0, total=10)
    result = engine.explain(_profile(), _mock_scholarship(), scores)
    assert len(result.gaps) == 9
    assert len(result.strengths) == 0


# --- _identify_strengths ---


def test_identify_strengths_from_details():
    engine = ExplanationEngine()
    scores = _scores()
    strengths = engine._identify_strengths(scores)
    assert len(strengths) == 9
    assert all(isinstance(s, str) for s in strengths)


def test_identify_strengths_uses_reason_text():
    engine = ExplanationEngine()
    scores = _scores()
    strengths = engine._identify_strengths(scores)
    # Reasons come from CriterionResult, not hardcoded generic text
    assert "Country 'Japan' matches target." in strengths


def test_identify_strengths_no_matched_returns_empty():
    engine = ExplanationEngine()
    scores = _scores(details=_gap_details())
    strengths = engine._identify_strengths(scores)
    assert len(strengths) == 0


# --- _identify_gaps ---


def test_identify_gaps_from_details():
    engine = ExplanationEngine()
    scores = _scores(details=_gap_details())
    gaps = engine._identify_gaps(scores)
    assert len(gaps) == 9
    assert all(isinstance(g, str) for g in gaps)


def test_identify_gaps_uses_reason_text():
    engine = ExplanationEngine()
    scores = _scores(details=_gap_details())
    gaps = engine._identify_gaps(scores)
    assert "Country 'Germany' does not match 'Japan'." in gaps


def test_identify_gaps_no_gaps_returns_empty():
    engine = ExplanationEngine()
    scores = _scores()  # perfect match
    gaps = engine._identify_gaps(scores)
    assert len(gaps) == 0


# --- _suggest_next_steps ---


def test_suggest_next_steps_gpa_gap():
    engine = ExplanationEngine()
    details = [_detail("gpa", 10, 15, False, "GPA below minimum.")]
    scores = _scores(details=details)
    steps = engine._suggest_next_steps(_mock_scholarship(), scores)
    assert any("GPA" in s for s in steps)


def test_suggest_next_steps_language_gap():
    engine = ExplanationEngine()
    details = [_detail("language", 0, 10, False, "IELTS required but missing.")]
    scores = _scores(details=details)
    steps = engine._suggest_next_steps(_mock_scholarship(), scores)
    assert any("IELTS" in s or "TOEFL" in s for s in steps)


def test_suggest_next_steps_country_gap():
    engine = ExplanationEngine()
    details = [_detail("country", 0, 20, False, "Country mismatch.")]
    scores = _scores(details=details)
    steps = engine._suggest_next_steps(_mock_scholarship(), scores)
    assert any("different country" in s for s in steps)


def test_suggest_next_steps_degree_gap():
    engine = ExplanationEngine()
    details = [_detail("degree", 0, 20, False, "Degree mismatch.")]
    scores = _scores(details=details)
    steps = engine._suggest_next_steps(_mock_scholarship(), scores)
    assert any("different degree" in s for s in steps)


def test_suggest_next_steps_field_gap():
    engine = ExplanationEngine()
    details = [_detail("field_of_study", 0, 20, False, "No field overlap.")]
    scores = _scores(details=details)
    steps = engine._suggest_next_steps(_mock_scholarship(), scores)
    # Fixed: now uses criterion name, not fragile string matching
    assert any("field of study" in s for s in steps)


def test_suggest_next_steps_research_gap():
    engine = ExplanationEngine()
    details = [_detail("research", 0, 5, False, "Research below requirement.")]
    scores = _scores(details=details)
    steps = engine._suggest_next_steps(_mock_scholarship(), scores)
    assert any("research" in s.lower() for s in steps)


def test_suggest_next_steps_work_gap():
    engine = ExplanationEngine()
    details = [_detail("work", 0, 3, False, "Work below requirement.")]
    scores = _scores(details=details)
    steps = engine._suggest_next_steps(_mock_scholarship(), scores)
    assert any("work experience" in s.lower() for s in steps)


def test_suggest_next_steps_includes_application_url():
    engine = ExplanationEngine()
    sch = _mock_scholarship(application_url="https://apply.example.com")
    scores = _scores(details=[])
    steps = engine._suggest_next_steps(sch, scores)
    assert any("https://apply.example.com" in s for s in steps)


def test_suggest_next_steps_fallback_to_official_url():
    engine = ExplanationEngine()
    sch = _mock_scholarship(application_url=None, official_page_url="https://official.example.com")
    scores = _scores(details=[])
    steps = engine._suggest_next_steps(sch, scores)
    assert any("https://official.example.com" in s for s in steps)


def test_suggest_next_steps_no_leadership_advice():
    """Leadership gaps don't produce next steps — it's a bonus, not a fixable gap."""
    engine = ExplanationEngine()
    details = [_detail("leadership", 0, 2, False, "No leadership.")]
    scores = _scores(details=details)
    steps = engine._suggest_next_steps(_mock_scholarship(application_url=None, official_page_url=None), scores)
    assert len(steps) == 0  # No advice for leadership, no URL


# --- _build_summary ---


def test_build_summary_excellent():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=95))
    assert "Excellent" in summary


def test_build_summary_strong():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=85))
    assert "Strong" in summary


def test_build_summary_good():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=75))
    assert "Good" in summary


def test_build_summary_moderate():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=65))
    assert "Moderate" in summary


def test_build_summary_low():
    engine = ExplanationEngine()
    summary = engine._build_summary(_scores(total=40))
    assert "Low" in summary


# --- Integration with ScoringEngine details ---


def test_mixed_match_has_both_strengths_and_gaps():
    """Partially matching profile produces both strengths and gaps."""
    engine = ExplanationEngine()
    details = [
        _detail("country", 20, 20, True, "Country matches."),
        _detail("degree", 20, 20, True, "Degree matches."),
        _detail("field_of_study", 0, 20, False, "No field overlap."),
        _detail("gpa", 10, 15, False, "GPA below minimum."),
        _detail("language", 10, 10, True, "IELTS meets requirement."),
        _detail("funding", 5, 5, True, "Funding matches."),
        _detail("research", 0, 5, False, "Research below requirement."),
        _detail("work", 3, 3, True, "Work meets requirement."),
        _detail("leadership", 2, 2, True, "Has leadership."),
    ]
    scores = _scores(details=details, field_of_study=0, gpa=10, research=0, total=70)
    result = engine.explain(_profile(), _mock_scholarship(), scores)
    assert len(result.strengths) == 6
    assert len(result.gaps) == 3
    assert len(result.next_steps) > 0


def test_explanation_never_recalculates_scores():
    """Verify the engine uses details as-is, never inspects raw float fields."""
    engine = ExplanationEngine()
    # Intentionally set float fields to all zeros but details say everything matched
    scores = _scores(
        details=_perfect_details(),
        country=0, degree=0, field_of_study=0, gpa=0,
        language=0, funding=0, research=0, work=0, leadership=0,
        total=0,
    )
    result = engine.explain(_profile(), _mock_scholarship(), scores)
    # Strengths come from details (all matched), not from float fields (all zero)
    assert len(result.strengths) == 9
    assert len(result.gaps) == 0
