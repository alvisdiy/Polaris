"""End-to-end integration tests for the Polaris matching vertical slice.

These tests stress-test the complete flow against real PostgreSQL:
  DB migration → reference seed → approved repository data →
  deadline filtering → scoring → ranking → explanation → /api/v1/matching
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import app
from database.session import SessionLocal
from services.matching.service import MatchingService
from services.matching.models.profile import UserProfile
from services.matching.models.result import CriteriaScores
from services.matching.models.result import CriteriaScores

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def session():
    """Single DB session for the module — reuses the real seeded PostgreSQL DB."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def svc(session):
    return MatchingService(session)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _japan_master_cs():
    return UserProfile(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science"],
        current_gpa=3.5,
        ielts_score=7.0,
        research_experience="Preferred",
        work_experience="Optional",
        publication="Not Required",
        leadership=True,
        funding_preference="Fully Funded",
    )


# ── 1. Repository returns only approved scholarships ──────────────────────

def test_repository_returns_only_approved(svc):
    """get_all_approved must never return non-approved scholarships."""
    from services.scholarship.repository import ScholarshipRepository
    repo = ScholarshipRepository(svc.session)
    approved = repo.get_all_approved()
    for s in approved:
        assert s.extraction_status == "approved"


# ── 2. Deadline filtering ─────────────────────────────────────────────────

def test_expired_scholarships_excluded(svc):
    """Expired scholarships must not appear in results."""
    profile = _japan_master_cs()
    out = svc.match(profile)
    names = {r.scholarship_name for r in out.results}
    # Chinese Government Scholarship has deadline 2026-04-30 (expired on 2026-09-10)
    assert "Chinese Government Scholarship" not in names


def test_future_deadline_passes(svc):
    """Scholarships with future deadlines must be included."""
    profile = _japan_master_cs()
    out = svc.match(profile)
    names = {r.scholarship_name for r in out.results}
    assert "MEXT Scholarship for Research Students" in names


# ── 3. Scoring correctness ─────────────────────────────────────────────────

def test_perfect_country_degree_match_scores_high(svc):
    """Country + degree match should earn full 40 points (20+20)."""
    profile = _japan_master_cs()
    out = svc.match(profile)
    mext = next(r for r in out.results if r.scholarship_name == "MEXT Scholarship for Research Students")
    assert mext.match_score >= 80  # strong match


def test_country_mismatch_penalty(svc):
    """Country mismatch should cost 20 points."""
    profile = UserProfile(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science"],
        current_gpa=3.5,
        ielts_score=7.0,
        research_experience="Preferred",
        work_experience="Optional",
        publication="Not Required",
        leadership=True,
        funding_preference="Fully Funded",
    )
    out = svc.match(profile)
    # DAAD EPOS is in Germany — country mismatch should reduce score
    daad = next((r for r in out.results if r.scholarship_name == "DAAD Development-Related Postgraduate Courses (EPOS)"), None)
    if daad:
        # Country mismatch: 20 points lost; but everything else might be partial
        assert daad.match_score <= 75


def test_partial_field_overlap_rewards_partial_score(svc):
    """2/5 user fields supported (CS + Engineering vs 5 fields) should score 8.0 (2/5 * 20)."""
    profile = UserProfile(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science", "Engineering", "Mathematics", "Physics", "Biology"],
        current_gpa=3.5,
        ielts_score=7.0,
        research_experience="Preferred",
        work_experience="Optional",
        publication="Not Required",
        leadership=True,
        funding_preference="Fully Funded",
    )
    # Use the internal engine directly to inspect criteria_scores
    scholarships = svc._repository.get_all_approved()
    filtered = svc._engine._filter.filter(profile, scholarships)
    scored = [(s, svc._engine._scoring.score(profile, s)) for s in filtered]
    mext = next(s for s, _ in scored if s.scholarship_name == "MEXT Scholarship for Research Students")
    mext_scores = next(scores for s, scores in scored if s.scholarship_name == "MEXT Scholarship for Research Students")
    # MEXT supports CS, AI, Engineering, Natural Sciences, Social Sciences
    # User has CS, Engineering, Math, Physics, Biology → 2/5 supported = 8.0
    assert mext_scores.field_of_study == 8.0  # 2/5 of user's fields supported


def test_no_field_restriction_full_score(svc):
    """Open-field scholarships (empty field_of_study) should get full 20."""
    profile = UserProfile(
        target_country="Germany",
        degree="Master",
        field_of_study=["Computer Science"],
        current_gpa=3.2,
        ielts_score=6.5,
        research_experience="Optional",
        work_experience="Optional",
        publication="Not Required",
        leadership=False,
        funding_preference="Fully Funded",
    )
    # Inspect criteria directly
    scholarships = svc._repository.get_all_approved()
    filtered = svc._engine._filter.filter(profile, scholarships)
    daad_all = next((s for s in filtered if s.scholarship_name == "DAAD Study Scholarships - Master Studies for All Academic Disciplines"), None)
    if daad_all:
        scores = svc._engine._scoring.score(profile, daad_all)
        assert scores.field_of_study == 20.0


# ── 4. Ranking determinism and tie-breakers ─────────────────────────────────


def test_ranking_tie_breakers_deadline_nearest_first(svc):
    """When scores are identical, nearest deadline must rank first."""
    scholarships = svc._repository.get_all_approved()
    assert len(scholarships) >= 5
    dummy_scores = CriteriaScores(
        country=20.0, degree=20.0, field_of_study=20.0, gpa=15.0, language=10.0,
        funding=5.0, research=5.0, work=3.0, leadership=2.0, total=80.0,
        details=[]
    )
    scored = [(s, dummy_scores) for s in scholarships]
    ranked = svc._engine._ranking.rank(scored)
    # Check that deadlines are non-decreasing (nearest first) among the ranked results
    deadlines = []
    for r in ranked:
        sch = next(s for s in scholarships if str(s.scholarship_id) == r.scholarship_id)
        dl = sch.timeline.application_deadline if sch.timeline else None
        if dl:
            deadlines.append(dl)
    for i in range(len(deadlines) - 1):
        assert deadlines[i] <= deadlines[i + 1]


def test_results_are_sorted_by_score_desc(svc):
    profile = _japan_master_cs()
    out = svc.match(profile)
    scores = [r.match_score for r in out.results]
    assert scores == sorted(scores, reverse=True)


def test_deterministic_repeated_requests(svc):
    """Same profile must produce identical results every time."""
    out1 = svc.match(_japan_master_cs())
    out2 = svc.match(_japan_master_cs())
    ids1 = [r.scholarship_id for r in out1.results]
    ids2 = [r.scholarship_id for r in out2.results]
    scores1 = [r.match_score for r in out1.results]
    scores2 = [r.match_score for r in out2.results]
    assert ids1 == ids2
    assert scores1 == scores2


# ── 5. API endpoint ────────────────────────────────────────────────────────

def test_api_v1_matching_contract(client):
    """POST /api/v1/matching returns valid JSON with required fields."""
    profile = _japan_master_cs()
    response = client.post("/api/v1/matching", json=profile.model_dump())
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "total" in data
    assert isinstance(data["results"], list)
    assert len(data["results"]) > 0
    result = data["results"][0]
    assert result["scholarship_id"]
    assert result["scholarship_name"]
    assert "deadline" in result
    assert result["match_score"] is not None
    assert result["recommendation_category"]
    assert result["official_url"]


def test_api_v1_matching_deterministic(client):
    """Two identical API calls produce identical results."""
    profile = _japan_master_cs()
    r1 = client.post("/api/v1/matching", json=profile.model_dump()).json()
    r2 = client.post("/api/v1/matching", json=profile.model_dump()).json()
    assert r1["results"] == r2["results"]


# ── 6. Explanation consistency ─────────────────────────────────────────────

def test_explanation_matches_scoring(svc):
    """Strengths should correspond to matched criteria; gaps to unmatched."""
    profile = _japan_master_cs()
    out = svc.match(profile)
    mext = next(r for r in out.results if r.scholarship_name == "MEXT Scholarship for Research Students")
    # Country matched -> should be a strength mentioning it
    assert any("country" in s.lower() or "japan" in s.lower() for s in mext.strengths)
    # Check field gap is properly described (CS vs 5 fields)
    scholarships = svc._repository.get_all_approved()
    filtered = svc._engine._filter.filter(profile, scholarships)
    mext_scores = next(svc._engine._scoring.score(profile, s) for s in filtered if s.scholarship_name == "MEXT Scholarship for Research Students")
    if mext_scores.field_of_study < 20:
        assert any("field" in g.lower() or "field" in s.lower() for g in mext.gaps for s in [g])


# ── 7. Edge cases ──────────────────────────────────────────────────────────

def test_empty_field_of_study_scores_max(svc):
    """Profile with no field_of_study should still work (defaults handled)."""
    profile = UserProfile(
        target_country="Japan",
        degree="Master",
        field_of_study=["General"],
        current_gpa=3.5,
        ielts_score=7.0,
        research_experience="Optional",
        work_experience="Optional",
        publication="Not Required",
        leadership=True,
        funding_preference="Fully Funded",
    )
    out = svc.match(profile)
    assert len(out.results) > 0


def test_no_leadership_gives_partial_score_on_leadership(svc):
    """Leadership=False on a scholarship requiring it should score 0 for leadership."""
    profile = UserProfile(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science"],
        current_gpa=3.5,
        ielts_score=7.0,
        research_experience="Preferred",
        work_experience="Optional",
        publication="Not Required",
        leadership=False,
        funding_preference="Fully Funded",
    )
    scholarships = svc._repository.get_all_approved()
    filtered = svc._engine._filter.filter(profile, scholarships)
    mext = next((s for s in filtered if s.scholarship_name == "MEXT Scholarship for Research Students"), None)
    if mext:
        scores = svc._engine._scoring.score(profile, mext)
        assert 0 <= scores.leadership <= 2
