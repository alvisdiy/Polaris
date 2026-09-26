"""Unit tests for ScoringEngine — no database required."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from services.matching.models.profile import UserProfile
from services.matching.scoring import ScoringEngine
from services.matching.scoring.criteria import CriteriaWeights
from services.matching.models.result import CriterionResult

pytestmark = pytest.mark.unit


def _mock_scholarship(**overrides) -> MagicMock:
    s = MagicMock()
    s.scholarship_id = overrides.get("scholarship_id", str(uuid.uuid4()))
    s.scholarship_name = overrides.get("scholarship_name", "Test Scholarship")
    s.degree = overrides.get("degree", "Master")
    s.funding_type = overrides.get("funding_type", "Fully Funded")
    s.field_of_study = overrides.get("field_of_study", ["Computer Science", "Engineering"])
    s.application_url = overrides.get("application_url", "https://example.com")
    s.official_page_url = overrides.get("official_page_url", "https://example.com")

    # Country mock
    country = MagicMock()
    country.name = overrides.get("country_name", "Japan")
    s.country = country

    # Requirement mock
    req = MagicMock()
    req.minimum_gpa = overrides.get("minimum_gpa", 3.0)
    req.ielts_required = overrides.get("ielts_required", True)
    req.minimum_ielts = overrides.get("minimum_ielts", 6.5)
    req.toefl_required = overrides.get("toefl_required", False)
    req.minimum_toefl = overrides.get("minimum_toefl", None)
    req.research_experience = overrides.get("research_experience", "Preferred")
    req.work_experience = overrides.get("work_experience", "Optional")
    s.requirement = req

    return s


def _profile(**overrides) -> UserProfile:
    defaults = dict(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science", "Engineering"],
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


# --- Score tests ---


def test_perfect_match():
    engine = ScoringEngine()
    sch = _mock_scholarship()
    scores = engine.score(_profile(), sch)
    assert scores.total == 100.0


def test_country_mismatch():
    engine = ScoringEngine()
    sch = _mock_scholarship(country_name="Germany")
    scores = engine.score(_profile(), sch)
    assert scores.country == 0.0


def test_degree_mismatch():
    engine = ScoringEngine()
    sch = _mock_scholarship(degree="PhD")
    scores = engine.score(_profile(), sch)
    assert scores.degree == 0.0


def test_partial_field_overlap():
    engine = ScoringEngine()
    sch = _mock_scholarship(field_of_study=["Computer Science"])
    profile = _profile(field_of_study=["Computer Science", "Engineering"])
    scores = engine.score(profile, sch)
    assert scores.field_of_study == 10.0  # 50% overlap


def test_no_field_restriction():
    engine = ScoringEngine()
    sch = _mock_scholarship(field_of_study=[])
    scores = engine.score(_profile(), sch)
    assert scores.field_of_study == 20.0  # Full score


def test_gpa_below_minimum():
    engine = ScoringEngine()
    sch = _mock_scholarship(minimum_gpa=3.0)
    profile = _profile(current_gpa=2.0)
    scores = engine.score(profile, sch)
    assert scores.gpa == round(15.0 * (2.0 / 3.0), 2)


def test_no_gpa_requirement():
    engine = ScoringEngine()
    sch = _mock_scholarship(minimum_gpa=None)
    scores = engine.score(_profile(current_gpa=2.0), sch)
    assert scores.gpa == 15.0


def test_ielts_required_but_no_score():
    engine = ScoringEngine()
    sch = _mock_scholarship(ielts_required=True, minimum_ielts=6.5)
    profile = _profile(ielts_score=None)
    scores = engine.score(profile, sch)
    assert scores.language == 0.0


def test_toefl_path():
    engine = ScoringEngine()
    sch = _mock_scholarship(ielts_required=False, toefl_required=True, minimum_toefl=90)
    profile = _profile(ielts_score=None, toefl_score=95)
    scores = engine.score(profile, sch)
    assert scores.language == 10.0


def test_toefl_below_minimum():
    engine = ScoringEngine()
    sch = _mock_scholarship(ielts_required=False, toefl_required=True, minimum_toefl=100)
    profile = _profile(ielts_score=None, toefl_score=80)
    scores = engine.score(profile, sch)
    assert scores.language == round(10.0 * (80.0 / 100.0), 2)


def test_no_language_requirement():
    engine = ScoringEngine()
    sch = _mock_scholarship(ielts_required=False, toefl_required=False)
    scores = engine.score(_profile(ielts_score=None), sch)
    assert scores.language == 10.0


def test_funding_mismatch():
    engine = ScoringEngine()
    sch = _mock_scholarship(funding_type="Partial Funded")
    scores = engine.score(_profile(), sch)
    assert scores.funding == 0.0


def test_research_one_level_below():
    engine = ScoringEngine()
    sch = _mock_scholarship(research_experience="Preferred")
    profile = _profile(research_experience="Optional")
    scores = engine.score(profile, sch)
    assert scores.research == 2.5


def test_research_two_levels_below():
    engine = ScoringEngine()
    sch = _mock_scholarship(research_experience="Required")
    profile = _profile(research_experience="Optional")
    scores = engine.score(profile, sch)
    assert scores.research == 0.0


def test_work_one_level_below():
    engine = ScoringEngine()
    sch = _mock_scholarship(work_experience="Preferred")
    profile = _profile(work_experience="Optional")
    scores = engine.score(profile, sch)
    assert scores.work == 1.5


def test_no_research_requirement():
    engine = ScoringEngine()
    sch = _mock_scholarship(research_experience=None)
    scores = engine.score(_profile(), sch)
    assert scores.research == 5.0


def test_no_work_requirement():
    engine = ScoringEngine()
    sch = _mock_scholarship(work_experience=None)
    scores = engine.score(_profile(), sch)
    assert scores.work == 3.0


def test_leadership_false():
    engine = ScoringEngine()
    scores = engine.score(_profile(leadership=False), _mock_scholarship())
    assert scores.leadership == 0.0


def test_no_requirement_object():
    engine = ScoringEngine()
    sch = _mock_scholarship()
    sch.requirement = None
    scores = engine.score(_profile(), sch)
    assert scores.gpa == 15.0
    assert scores.language == 10.0
    assert scores.research == 5.0
    assert scores.work == 3.0


def test_custom_weights():
    weights = CriteriaWeights(
        country=30, degree=10, field_of_study=10, gpa=10,
        language=10, funding=10, research=10, work=5, leadership=5,
    )
    engine = ScoringEngine(weights=weights)
    sch = _mock_scholarship()
    scores = engine.score(_profile(), sch)
    assert scores.total == 100.0
    assert scores.country == 30.0


# --- CriterionResult / details tests ---


def test_details_contains_all_criteria():
    engine = ScoringEngine()
    scores = engine.score(_profile(), _mock_scholarship())
    assert len(scores.details) == 9
    names = {d.criterion for d in scores.details}
    assert names == {
        "country", "degree", "field_of_study", "gpa", "language",
        "funding", "research", "work", "leadership",
    }


def test_details_scores_sum_to_total():
    engine = ScoringEngine()
    scores = engine.score(_profile(), _mock_scholarship())
    assert round(sum(d.score for d in scores.details), 2) == scores.total


def test_perfect_match_all_reasons_present():
    engine = ScoringEngine()
    scores = engine.score(_profile(), _mock_scholarship())
    for detail in scores.details:
        assert isinstance(detail, CriterionResult)
        assert detail.matched is True
        assert detail.score == detail.weight
        assert len(detail.reason) > 0


def test_country_mismatch_reason():
    engine = ScoringEngine()
    sch = _mock_scholarship(country_name="Germany")
    scores = engine.score(_profile(), sch)
    country_detail = next(d for d in scores.details if d.criterion == "country")
    assert country_detail.matched is False
    assert "Germany" in country_detail.reason
    assert "Japan" in country_detail.reason


def test_degree_mismatch_reason():
    engine = ScoringEngine()
    sch = _mock_scholarship(degree="PhD")
    scores = engine.score(_profile(), sch)
    degree_detail = next(d for d in scores.details if d.criterion == "degree")
    assert degree_detail.matched is False
    assert "PhD" in degree_detail.reason


def test_field_no_overlap_reason():
    engine = ScoringEngine()
    sch = _mock_scholarship(field_of_study=["Biology"])
    scores = engine.score(_profile(), sch)
    field_detail = next(d for d in scores.details if d.criterion == "field_of_study")
    assert field_detail.matched is False
    assert field_detail.score == 0.0
    assert "No overlap" in field_detail.reason


def test_gpa_below_minimum_reason():
    engine = ScoringEngine()
    sch = _mock_scholarship(minimum_gpa=3.5)
    profile = _profile(current_gpa=3.0)
    scores = engine.score(profile, sch)
    gpa_detail = next(d for d in scores.details if d.criterion == "gpa")
    assert gpa_detail.matched is False
    assert "3.0" in gpa_detail.reason
    assert "3.5" in gpa_detail.reason


def test_language_missing_reason():
    engine = ScoringEngine()
    sch = _mock_scholarship(ielts_required=True, minimum_ielts=6.5)
    profile = _profile(ielts_score=None)
    scores = engine.score(profile, sch)
    lang_detail = next(d for d in scores.details if d.criterion == "language")
    assert lang_detail.matched is False
    assert "no IELTS score" in lang_detail.reason


def test_leadership_reason():
    engine = ScoringEngine()
    scores = engine.score(_profile(leadership=False), _mock_scholarship())
    lead_detail = next(d for d in scores.details if d.criterion == "leadership")
    assert lead_detail.matched is False
    assert "no leadership" in lead_detail.reason


# --- Zero score / mixed score / fully funded tests ---


def test_zero_score():
    """Every criterion mismatches — total should be 0."""
    engine = ScoringEngine()
    sch = _mock_scholarship(
        country_name="Germany",
        degree="PhD",
        field_of_study=["Biology"],
        minimum_gpa=4.0,
        ielts_required=True,
        minimum_ielts=9.0,
        funding_type="Tuition Only",
        research_experience="Required",
        work_experience="Required",
    )
    profile = _profile(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science"],
        current_gpa=0.0,
        ielts_score=None,
        research_experience="Not Required",
        work_experience="Not Required",
        leadership=False,
        funding_preference="Fully Funded",
    )
    scores = engine.score(profile, sch)
    assert scores.total == 0.0
    for detail in scores.details:
        assert detail.matched is False
        assert detail.score == 0.0


def test_mixed_score():
    """Some criteria match, some don't — verify partial total."""
    engine = ScoringEngine()
    sch = _mock_scholarship(
        country_name="Japan",       # match: 20
        degree="Master",            # match: 20
        field_of_study=["Biology"], # no overlap: 0
        minimum_gpa=3.0,            # 2.5/3.0 ratio: 12.5
        ielts_required=False,       # no req: 10
        funding_type="Partial Funded",  # mismatch: 0
        research_experience=None,   # no req: 5
        work_experience=None,       # no req: 3
    )
    profile = _profile(
        current_gpa=2.5,
        field_of_study=["Computer Science"],
        funding_preference="Fully Funded",
        leadership=True,            # bonus: 2
    )
    scores = engine.score(profile, sch)
    expected = 20 + 20 + 0 + round(15 * (2.5 / 3.0), 2) + 10 + 0 + 5 + 3 + 2
    assert scores.total == round(expected, 2)


def test_fully_funded_match():
    engine = ScoringEngine()
    sch = _mock_scholarship(funding_type="Fully Funded")
    profile = _profile(funding_preference="Fully Funded")
    scores = engine.score(profile, sch)
    assert scores.funding == 5.0
    funding_detail = next(d for d in scores.details if d.criterion == "funding")
    assert funding_detail.matched is True


def test_partial_funded_match():
    engine = ScoringEngine()
    sch = _mock_scholarship(funding_type="Partial Funded")
    profile = _profile(funding_preference="Partial Funded")
    scores = engine.score(profile, sch)
    assert scores.funding == 5.0


def test_leadership_bonus():
    """Leadership is a bonus — profile with leadership gets 2 extra points."""
    engine = ScoringEngine()
    sch = _mock_scholarship()
    with_lead = engine.score(_profile(leadership=True), sch)
    without_lead = engine.score(_profile(leadership=False), sch)
    assert with_lead.leadership == 2.0
    assert without_lead.leadership == 0.0
    assert with_lead.total - without_lead.total == 2.0
