"""Unit tests for ScholarshipIntelligenceEngine — no database required."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from services.matching.explanation import ExplanationEngine
from services.matching.filter import FilterEngine
from services.matching.models.profile import UserProfile
from services.matching.models.result import CriteriaScores, MatchExplanation, MatchResult
from services.matching.orchestrator import ScholarshipIntelligenceEngine
from services.matching.ranking import RankingEngine
from services.matching.scoring import ScoringEngine

pytestmark = pytest.mark.unit


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


def _mock_scholarship(name: str = "Test Scholarship") -> MagicMock:
    s = MagicMock()
    s.scholarship_id = str(uuid.uuid4())
    s.scholarship_name = name
    s.degree = "Master"
    s.funding_type = "Fully Funded"
    s.field_of_study = ["Computer Science"]
    s.application_url = "https://example.com"
    s.official_page_url = "https://example.com"
    s.extraction_status = "approved"

    country = MagicMock()
    country.name = "Japan"
    s.country = country

    timeline = MagicMock()
    from datetime import date

    timeline.application_deadline = date(2099, 12, 31)
    s.timeline = timeline

    req = MagicMock()
    req.minimum_gpa = 3.0
    req.ielts_required = True
    req.minimum_ielts = 6.5
    req.toefl_required = False
    req.minimum_toefl = None
    req.research_experience = "Preferred"
    req.work_experience = "Optional"
    s.requirement = req

    return s


def test_orchestrator_match_returns_results():
    engine = ScholarshipIntelligenceEngine()
    scholarships = [_mock_scholarship("Sch A"), _mock_scholarship("Sch B")]
    results = engine.match(_profile(), scholarships)
    assert len(results) == 2
    assert all(isinstance(r, MatchResult) for r in results)


def test_orchestrator_match_sorted_by_score():
    engine = ScholarshipIntelligenceEngine()
    scholarships = [_mock_scholarship("Sch A"), _mock_scholarship("Sch B")]
    results = engine.match(_profile(), scholarships)
    scores = [r.match_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_orchestrator_match_with_explanations():
    engine = ScholarshipIntelligenceEngine()
    scholarships = [_mock_scholarship()]
    results = engine.match(_profile(), scholarships)
    assert len(results[0].explanation.strengths) > 0
    valid_categories = ("Excellent Match", "Strong Match", "Good Match", "Moderate Match", "Low Match")
    assert results[0].recommendation_category in valid_categories


def test_orchestrator_empty_scholarships():
    engine = ScholarshipIntelligenceEngine()
    results = engine.match(_profile(), [])
    assert results == []


def test_orchestrator_custom_engines():
    filter_engine = MagicMock(spec=FilterEngine)
    scoring_engine = MagicMock(spec=ScoringEngine)
    ranking_engine = MagicMock(spec=RankingEngine)
    explanation_engine = MagicMock(spec=ExplanationEngine)

    sch = _mock_scholarship()
    filter_engine.filter.return_value = [sch]

    scores = CriteriaScores(
        country=20, degree=20, field_of_study=20, gpa=15,
        language=10, funding=5, research=5, work=3, leadership=2, total=100,
    )
    scoring_engine.score.return_value = scores

    result = MatchResult(
        scholarship_id=sch.scholarship_id,
        scholarship_name=sch.scholarship_name,
        match_score=100.0,
        recommendation_category="Strongly Recommended",
        criteria_scores=scores,
        explanation=MatchExplanation(summary="", strengths=[], gaps=[], next_steps=[]),
        official_url="https://example.com",
    )
    ranking_engine.rank_with_total.return_value = ([result], 1)

    explanation = MatchExplanation(summary="Excellent match", strengths=["All good"], gaps=[], next_steps=[])
    explanation_engine.explain.return_value = explanation

    engine = ScholarshipIntelligenceEngine(
        filter_engine=filter_engine,
        scoring_engine=scoring_engine,
        ranking_engine=ranking_engine,
        explanation_engine=explanation_engine,
    )

    results = engine.match(_profile(), [sch])
    assert len(results) == 1
    filter_engine.filter.assert_called_once()
    scoring_engine.score.assert_called_once()
    ranking_engine.rank_with_total.assert_called_once()
    explanation_engine.explain.assert_called_once()
