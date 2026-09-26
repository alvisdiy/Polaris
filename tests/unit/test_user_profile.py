"""Tests for UserProfile domain model (M3.1)."""

import pytest
from pydantic import ValidationError

from services.matching.models import CriteriaScores, GapReport, MatchExplanation, MatchResult, UserProfile
from services.matching.profile import ProfileNormalizer, ProfileValidator

pytestmark = pytest.mark.unit


class TestUserProfileCreation:
    """Pydantic model creation and validation."""

    def test_valid_profile(self):
        profile = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["Computer Science", "AI"],
            current_gpa=3.7,
            ielts_score=7.0,
            toefl_score=None,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        assert profile.target_country == "Japan"
        assert profile.degree == "Master"
        assert len(profile.field_of_study) == 2
        assert profile.current_gpa == 3.7
        assert profile.ielts_score == 7.0
        assert profile.toefl_score is None
        assert profile.leadership is True

    def test_gpa_out_of_range(self):
        with pytest.raises(ValidationError) as exc_info:
            UserProfile(
                target_country="Japan",
                degree="Master",
                field_of_study=["CS"],
                current_gpa=5.0,
                research_experience="Optional",
                work_experience="Optional",
                publication="Optional",
                leadership=False,
                funding_preference="Fully Funded",
            )
        assert "current_gpa" in str(exc_info.value)

    def test_empty_field_of_study(self):
        with pytest.raises(ValidationError) as exc_info:
            UserProfile(
                target_country="Japan",
                degree="Master",
                field_of_study=[],
                current_gpa=3.0,
                research_experience="Optional",
                work_experience="Optional",
                publication="Optional",
                leadership=False,
                funding_preference="Fully Funded",
            )
        assert "field_of_study" in str(exc_info.value)

    def test_immutable(self):
        profile = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["CS"],
            current_gpa=3.5,
            research_experience="Optional",
            work_experience="Optional",
            publication="Optional",
            leadership=False,
            funding_preference="Fully Funded",
        )
        with pytest.raises(Exception):
            profile.target_country = "Germany"


class TestProfileValidator:
    """ProfileValidator business rule validation."""

    def setup_method(self):
        self.validator = ProfileValidator()

    def test_valid_profile(self):
        profile = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["CS"],
            current_gpa=3.7,
            ielts_score=7.0,
            research_experience="Preferred",
            work_experience="Optional",
            publication="Not Required",
            leadership=True,
            funding_preference="Fully Funded",
        )
        assert self.validator.validate(profile) == []

    def test_invalid_degree(self):
        profile = UserProfile(
            target_country="Japan",
            degree="SuperPhD",
            field_of_study=["CS"],
            current_gpa=3.0,
            research_experience="Optional",
            work_experience="Optional",
            publication="Optional",
            leadership=False,
            funding_preference="Fully Funded",
        )
        errors = self.validator.validate(profile)
        assert len(errors) == 1
        assert "degree" in errors[0].lower()

    def test_invalid_funding(self):
        profile = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["CS"],
            current_gpa=3.0,
            research_experience="Optional",
            work_experience="Optional",
            publication="Optional",
            leadership=False,
            funding_preference="Free Money",
        )
        errors = self.validator.validate(profile)
        assert len(errors) == 1
        assert "funding" in errors[0].lower()

    def test_invalid_experience(self):
        profile = UserProfile(
            target_country="Japan",
            degree="Master",
            field_of_study=["CS"],
            current_gpa=3.0,
            research_experience="Maybe",
            work_experience="Optional",
            publication="Optional",
            leadership=False,
            funding_preference="Fully Funded",
        )
        errors = self.validator.validate(profile)
        assert len(errors) == 1
        assert "research_experience" in errors[0]

    def test_multiple_errors(self):
        profile = UserProfile(
            target_country="",
            degree="MBA",
            field_of_study=["Business"],
            current_gpa=3.0,
            research_experience="Sometimes",
            work_experience="Often",
            publication="Never",
            leadership=False,
            funding_preference="Scholarship",
        )
        errors = self.validator.validate(profile)
        assert len(errors) >= 4


class TestProfileNormalizer:
    """ProfileNormalizer alias resolution."""

    def setup_method(self):
        self.normalizer = ProfileNormalizer()

    def test_degree_aliases(self):
        profile = UserProfile(
            target_country="japan",
            degree="master's",
            field_of_study=["ai", "cs"],
            current_gpa=3.5,
            research_experience="preferred",
            work_experience="optional",
            publication="not required",
            leadership=True,
            funding_preference="full",
        )
        normalized = self.normalizer.normalize(profile)
        assert normalized.degree == "Master"
        assert normalized.target_country == "Japan"
        assert normalized.funding_preference == "Fully Funded"

    def test_field_aliases(self):
        profile = UserProfile(
            target_country="japan",
            degree="master's",
            field_of_study=["ai", "cs"],
            current_gpa=3.5,
            research_experience="preferred",
            work_experience="optional",
            publication="not required",
            leadership=True,
            funding_preference="full",
        )
        normalized = self.normalizer.normalize(profile)
        assert "Artificial Intelligence" in normalized.field_of_study
        assert "Computer Science" in normalized.field_of_study

    def test_experience_aliases(self):
        profile = UserProfile(
            target_country="japan",
            degree="master's",
            field_of_study=["ai", "cs"],
            current_gpa=3.5,
            research_experience="preferred",
            work_experience="optional",
            publication="not required",
            leadership=True,
            funding_preference="full",
        )
        normalized = self.normalizer.normalize(profile)
        assert normalized.research_experience == "Preferred"
        assert normalized.work_experience == "Optional"
        assert normalized.publication == "Not Required"

    def test_idempotency(self):
        profile = UserProfile(
            target_country="japan",
            degree="master's",
            field_of_study=["ai", "cs"],
            current_gpa=3.5,
            research_experience="preferred",
            work_experience="optional",
            publication="not required",
            leadership=True,
            funding_preference="full",
        )
        normalized = self.normalizer.normalize(profile)
        double = self.normalizer.normalize(normalized)
        assert normalized == double


class TestResultModels:
    """Result model creation."""

    def test_criteria_scores(self):
        scores = CriteriaScores(
            country=20,
            degree=20,
            field_of_study=15,
            gpa=12,
            language=8,
            funding=5,
            research=3,
            work=2,
            leadership=2,
            total=87,
        )
        assert scores.total == 87

    def test_gap_report(self):
        gap = GapReport(field="minimum_gpa", requirement="3.5", user_value="3.2", gap_description="GPA below minimum")
        assert gap.field == "minimum_gpa"

    def test_explanation(self):
        explanation = MatchExplanation(
            summary="Strong match",
            strengths=["Country match", "Degree match"],
            gaps=["GPA below minimum"],
            next_steps=["Improve GPA", "Visit application page"],
        )
        assert len(explanation.strengths) == 2

    def test_match_result(self):
        scores = CriteriaScores(
            country=20,
            degree=20,
            field_of_study=15,
            gpa=12,
            language=8,
            funding=5,
            research=3,
            work=2,
            leadership=2,
            total=87,
        )
        result = MatchResult(
            scholarship_id="test-id",
            scholarship_name="Test Scholarship",
            match_score=87.0,
            recommendation_category="Strong Match",
            criteria_scores=scores,
            explanation=MatchExplanation(summary="", strengths=["Country match"], gaps=[]),
            official_url="https://example.com",
        )
        assert result.match_score == 87.0
