"""Tests for RankingEngine (M3.4)."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from services.matching.models.result import CriteriaScores
from services.matching.ranking import RankingEngine

pytestmark = pytest.mark.unit


def _make_scholarship(name, deadline_days, funding="Fully Funded"):
    sch = MagicMock()
    sch.scholarship_name = name
    sch.scholarship_id = name
    sch.funding_type = funding
    sch.official_page_url = "https://example.com"
    sch.application_url = None
    sch.timeline = MagicMock()
    sch.timeline.application_deadline = date.today() + timedelta(days=deadline_days) if deadline_days else None
    sch.requirement = MagicMock()
    sch.benefit = MagicMock()
    # Count non-null for completeness
    sch.scholarship_name = name
    sch.degree = "Master"
    sch.field_of_study = ["CS"]
    return sch


class TestRankingEngine:
    """RankingEngine sort and Top-N tests."""

    def test_sorted_by_score_descending(self):
        engine = RankingEngine()
        scored = [
            (_make_scholarship("Low", 90), CriteriaScores(total=50)),
            (_make_scholarship("High", 90), CriteriaScores(total=90)),
            (_make_scholarship("Mid", 90), CriteriaScores(total=70)),
        ]
        results = engine.rank(scored)
        assert results[0].match_score >= results[1].match_score >= results[2].match_score

    def test_top_n_truncation(self):
        engine = RankingEngine(top_n=2)
        scored = [
            (_make_scholarship("A", 90), CriteriaScores(total=90)),
            (_make_scholarship("B", 90), CriteriaScores(total=80)),
            (_make_scholarship("C", 90), CriteriaScores(total=70)),
        ]
        results = engine.rank(scored)
        assert len(results) == 2

    def test_deadline_tiebreaker(self):
        engine = RankingEngine()
        scored = [
            (_make_scholarship("Far", 180), CriteriaScores(total=90)),
            (_make_scholarship("Near", 30), CriteriaScores(total=90)),
        ]
        results = engine.rank(scored)
        # Near deadline should rank higher among equal scores
        assert results[0].scholarship_name == "Near"

    def test_funding_type_tiebreaker(self):
        engine = RankingEngine()
        scored = [
            (_make_scholarship("Partial", 90, "Partial Funded"), CriteriaScores(total=90)),
            (_make_scholarship("Full", 90, "Fully Funded"), CriteriaScores(total=90)),
        ]
        results = engine.rank(scored)
        assert results[0].scholarship_name == "Full"

    def test_recommendation_categories(self):
        engine = RankingEngine()
        scored = [
            (_make_scholarship("Excellent", 90), CriteriaScores(total=95)),
            (_make_scholarship("Strong", 90), CriteriaScores(total=85)),
            (_make_scholarship("Good", 90), CriteriaScores(total=75)),
            (_make_scholarship("Moderate", 90), CriteriaScores(total=65)),
            (_make_scholarship("Low", 90), CriteriaScores(total=45)),
        ]
        results = engine.rank(scored)
        categories = {r.scholarship_name: r.recommendation_category for r in results}
        assert categories["Excellent"] == "Excellent Match"
        assert categories["Strong"] == "Strong Match"
        assert categories["Good"] == "Good Match"
        assert categories["Moderate"] == "Moderate Match"
        assert categories["Low"] == "Low Match"
