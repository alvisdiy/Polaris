"""Unit tests for MatchingService — no database required."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from services.matching.models.profile import UserProfile
from services.matching.models.result import (
    CriteriaScores,
    CriterionResult,
    MatchExplanation,
    MatchResult,
)
from services.matching.orchestrator import ScholarshipIntelligenceEngine
from services.matching.profile import ProfileNormalizer, ProfileValidator
from services.matching.service import MatchingOutput, MatchingService

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_scholarship(**overrides) -> MagicMock:
    """Create a mock Scholarship with all required relationships."""
    s = MagicMock()
    s.scholarship_id = overrides.get("scholarship_id", str(uuid.uuid4()))
    s.scholarship_name = overrides.get("scholarship_name", "Test Scholarship")
    s.degree = overrides.get("degree", "Master")
    s.funding_type = overrides.get("funding_type", "Fully Funded")
    s.field_of_study = overrides.get("field_of_study", ["Computer Science"])
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
    req.gre_required = overrides.get("gre_required", False)
    req.minimum_gre = overrides.get("minimum_gre", None)
    req.age_limit = overrides.get("age_limit", None)
    req.work_experience = overrides.get("work_experience", "Optional")
    req.research_experience = overrides.get("research_experience", "Preferred")
    req.publication = overrides.get("publication", "Not Required")
    req.recommendation_letter = overrides.get("recommendation_letter", False)
    req.motivation_letter = overrides.get("motivation_letter", False)
    req.cv_required = overrides.get("cv_required", False)
    req.passport_required = overrides.get("passport_required", False)
    s.requirement = req

    # Benefit mock
    benefit = MagicMock()
    benefit.tuition_fee = overrides.get("tuition_fee", True)
    benefit.monthly_allowance = overrides.get("monthly_allowance", True)
    benefit.accommodation = overrides.get("accommodation", True)
    benefit.health_insurance = overrides.get("health_insurance", True)
    benefit.travel_ticket = overrides.get("travel_ticket", True)
    benefit.research_grant = overrides.get("research_grant", False)
    s.benefit = benefit

    # Timeline mock
    timeline = MagicMock()
    timeline.application_open = overrides.get("application_open", None)
    timeline.application_deadline = overrides.get("application_deadline", None)
    timeline.application_cycle = overrides.get("application_cycle", None)
    timeline.interview_date = overrides.get("interview_date", None)
    timeline.result_date = overrides.get("result_date", None)
    timeline.study_start = overrides.get("study_start", None)
    s.timeline = timeline

    # Provider mock
    provider = MagicMock()
    provider.provider_name = overrides.get("provider_name", "MEXT")
    s.provider = provider

    return s


def _profile(**overrides) -> UserProfile:
    """Create a valid UserProfile for testing."""
    defaults = dict(
        target_country="Japan",
        degree="Master",
        field_of_study=["Computer Science"],
        current_gpa=3.5,
        ielts_score=7.0,
        toefl_score=None,
        research_experience="Preferred",
        work_experience="Optional",
        publication="Not Required",
        leadership=True,
        funding_preference="Fully Funded",
    )
    defaults.update(overrides)
    return UserProfile(**defaults)


def _mock_result(scholarship_id: str = None, score: float = 85.0) -> MatchResult:
    """Create a mock MatchResult."""
    sid = scholarship_id or str(uuid.uuid4())
    return MatchResult(
        scholarship_id=sid,
        scholarship_name="Test Scholarship",
        match_score=score,
        recommendation_category="Strong Match",
        criteria_scores=CriteriaScores(
            country=20.0,
            degree=20.0,
            field_of_study=20.0,
            gpa=15.0,
            language=10.0,
            funding=0.0,
            research=0.0,
            work=0.0,
            leadership=0.0,
            total=score,
            details=[
                CriterionResult("country", 20.0, 20.0, True, "Match"),
                CriterionResult("degree", 20.0, 20.0, True, "Match"),
                CriterionResult("field_of_study", 20.0, 20.0, True, "Match"),
                CriterionResult("gpa", 15.0, 15.0, True, "Match"),
                CriterionResult("language", 10.0, 10.0, True, "Match"),
                CriterionResult("funding", 0.0, 5.0, False, "No match"),
                CriterionResult("research", 0.0, 5.0, False, "No match"),
                CriterionResult("work", 0.0, 3.0, False, "No match"),
                CriterionResult("leadership", 0.0, 2.0, False, "No match"),
            ],
        ),
        explanation=MatchExplanation(
            summary=f"Strong match ({score}/100). You meet the core requirements with minor gaps.",
            strengths=["Strength 1"],
            gaps=[],
            next_steps=["Visit the official application page: https://example.com"],
        ),
        official_url="https://example.com",
    )


# ---------------------------------------------------------------------------
# Tests — Instantiation
# ---------------------------------------------------------------------------

class TestMatchingServiceInstantiation:
    """Test MatchingService construction and DI."""

    def test_accepts_all_dependencies(self):
        """All dependencies are accepted via constructor for DI."""
        session = MagicMock()
        engine = MagicMock(spec=ScholarshipIntelligenceEngine)
        validator = MagicMock(spec=ProfileValidator)
        normalizer = MagicMock(spec=ProfileNormalizer)
        repo = MagicMock()

        service = MatchingService(
            session=session,
            engine=engine,
            validator=validator,
            normalizer=normalizer,
            repository=repo,
        )

        assert service._session is session
        assert service._engine is engine
        assert service._validator is validator
        assert service._normalizer is normalizer
        assert service._repository is repo

    def test_creates_defaults_when_not_provided(self):
        """Defaults are created for all optional dependencies."""
        session = MagicMock()

        service = MatchingService(session=session)

        assert isinstance(service._engine, ScholarshipIntelligenceEngine)
        assert isinstance(service._validator, ProfileValidator)
        assert isinstance(service._normalizer, ProfileNormalizer)
        # Repository gets the session passed through
        assert service._repository.session is session

    def test_session_property_returns_injected_session(self):
        """The session property exposes the injected session."""
        session = MagicMock()
        service = MatchingService(session=session)
        assert service.session is session


# ---------------------------------------------------------------------------
# Tests — Successful Matching Flow
# ---------------------------------------------------------------------------

class TestMatchingServiceMatch:
    """Test the happy-path match() execution."""

    def test_validates_profile_before_processing(self):
        """match() raises ValueError for invalid profiles."""
        session = MagicMock()
        validator = MagicMock(spec=ProfileValidator)
        validator.validate.return_value = ["degree is invalid"]

        service = MatchingService(
            session=session,
            validator=validator,
        )

        invalid_profile = _profile(degree="InvalidDegree")
        with pytest.raises(ValueError, match="Profile validation failed"):
            service.match(invalid_profile)

        # Validator was called, engine was not
        validator.validate.assert_called_once_with(invalid_profile)

    def test_normalizes_valid_profile(self):
        """A valid profile is normalized before pipeline execution."""
        session = MagicMock()
        validator = MagicMock(spec=ProfileValidator)
        validator.validate.return_value = []
        normalizer = MagicMock(spec=ProfileNormalizer)
        normalized_profile = _profile(degree="Master")
        normalizer.normalize.return_value = normalized_profile

        repo = MagicMock()
        repo.get_all_approved.return_value = []

        engine = MagicMock(spec=ScholarshipIntelligenceEngine)
        engine.match.return_value = []

        service = MatchingService(
            session=session,
            validator=validator,
            normalizer=normalizer,
            repository=repo,
            engine=engine,
        )

        raw_profile = _profile(degree="master")  # lowercase — needs normalization
        service.match(raw_profile)

        # Normalizer was called with the raw profile
        normalizer.normalize.assert_called_once_with(raw_profile)
        # Engine received the normalized profile
        engine.match.assert_called_once_with(normalized_profile, [])

    def test_loads_approved_scholarships_from_repository(self):
        """match() loads scholarships from the repository."""
        session = MagicMock()
        validator = MagicMock(spec=ProfileValidator)
        validator.validate.return_value = []
        normalizer = MagicMock(spec=ProfileNormalizer)
        normalizer.normalize.return_value = _profile()

        scholarships = [_mock_scholarship(), _mock_scholarship()]
        repo = MagicMock()
        repo.get_all_approved.return_value = scholarships

        engine = MagicMock(spec=ScholarshipIntelligenceEngine)
        engine.match.return_value = []

        service = MatchingService(
            session=session,
            validator=validator,
            normalizer=normalizer,
            repository=repo,
            engine=engine,
        )

        service.match(_profile())

        repo.get_all_approved.assert_called_once()
        engine.match.assert_called_once()
        call_args = engine.match.call_args
        _, called_scholarships = call_args[0]
        assert called_scholarships == scholarships

    def test_returns_matching_output_with_results(self):
        """match() returns a MatchingOutput with results from the engine."""
        session = MagicMock()
        validator = MagicMock(spec=ProfileValidator)
        validator.validate.return_value = []
        normalizer = MagicMock(spec=ProfileNormalizer)
        normalizer.normalize.return_value = _profile()

        sid = str(uuid.uuid4())
        scholarships = [_mock_scholarship(scholarship_id=sid)]
        repo = MagicMock()
        repo.get_all_approved.return_value = scholarships

        expected_results = [_mock_result(scholarship_id=sid, score=85.0)]
        engine = MagicMock(spec=ScholarshipIntelligenceEngine)
        engine.match.return_value = expected_results

        service = MatchingService(
            session=session,
            validator=validator,
            normalizer=normalizer,
            repository=repo,
            engine=engine,
        )

        output = service.match(_profile())

        assert isinstance(output, MatchingOutput)
        assert len(output.results) == 1
        mapped = output.results[0]
        expected = expected_results[0]
        assert mapped.scholarship_id == expected.scholarship_id
        assert mapped.scholarship_name == expected.scholarship_name
        assert mapped.match_score == expected.match_score
        assert mapped.recommendation_category == expected.recommendation_category
        assert mapped.summary == expected.explanation.summary
        assert mapped.strengths == expected.explanation.strengths
        assert mapped.gaps == expected.explanation.gaps
        assert mapped.next_steps == expected.explanation.next_steps
        assert mapped.official_url == expected.official_url
        assert mapped.provider_name == "MEXT"
        assert mapped.country == "Japan"
        assert output.total_filtered == 0  # none filtered when len(results)==len(scholarships)


# ---------------------------------------------------------------------------
# Tests — Empty and Edge Cases
# ---------------------------------------------------------------------------

class TestMatchingServiceEdgeCases:
    """Test edge cases: empty results, no scholarships, etc."""

    def test_handles_empty_scholarship_list(self):
        """match() handles an empty scholarship list gracefully."""
        session = MagicMock()
        validator = MagicMock(spec=ProfileValidator)
        validator.validate.return_value = []
        normalizer = MagicMock(spec=ProfileNormalizer)
        normalizer.normalize.return_value = _profile()

        repo = MagicMock()
        repo.get_all_approved.return_value = []

        engine = MagicMock(spec=ScholarshipIntelligenceEngine)
        engine.match.return_value = []

        service = MatchingService(
            session=session,
            validator=validator,
            normalizer=normalizer,
            repository=repo,
            engine=engine,
        )

        output = service.match(_profile())

        assert output.results == []
        assert output.total_filtered == 0

    def test_total_filtered_reflects_deadline_filtering(self):
        """total_filtered counts scholarships removed by the Filter stage."""
        session = MagicMock()
        validator = MagicMock(spec=ProfileValidator)
        validator.validate.return_value = []
        normalizer = MagicMock(spec=ProfileNormalizer)
        normalizer.normalize.return_value = _profile()

        # Repository returns 10 scholarships
        scholarships = [_mock_scholarship() for _ in range(10)]
        repo = MagicMock()
        repo.get_all_approved.return_value = scholarships

        # Engine only returns 7 (3 were filtered by deadline)
        engine = MagicMock(spec=ScholarshipIntelligenceEngine)
        engine.match.return_value = [
            _mock_result(scholarship_id=scholarships[i].scholarship_id, score=80.0)
            for i in range(7)
        ]

        service = MatchingService(
            session=session,
            validator=validator,
            normalizer=normalizer,
            repository=repo,
            engine=engine,
        )

        output = service.match(_profile())

        assert len(output.results) == 7
        assert output.total_filtered == 3

    def test_validation_error_contains_all_error_messages(self):
        """Validation errors include all field-level errors, not just the first."""
        session = MagicMock()
        validator = MagicMock(spec=ProfileValidator)
        validator.validate.return_value = [
            "degree must be one of: Bachelor, Master, PhD",
            "target_country cannot be empty",
        ]

        service = MatchingService(
            session=session,
            validator=validator,
        )

        with pytest.raises(ValueError) as exc_info:
            service.match(_profile())
        error_msg = str(exc_info.value)
        assert "degree must be one of" in error_msg
        assert "target_country cannot be empty" in error_msg


# ---------------------------------------------------------------------------
# Tests — Data Classes
# ---------------------------------------------------------------------------

class TestMatchingOutput:
    """Test MatchingOutput dataclass."""

    def test_matching_output_is_frozen(self):
        """MatchingOutput is immutable."""
        output = MatchingOutput(results=[], total_filtered=0)
        with pytest.raises(AttributeError):
            output.results = [_mock_result()]  # type: ignore

    def test_matching_output_stores_results(self):
        """MatchingOutput holds the results list."""
        results = [_mock_result(score=90.0), _mock_result(score=75.0)]
        output = MatchingOutput(results=results, total_filtered=0)
        assert len(output.results) == 2
        assert output.results[0].match_score == 90.0
        assert output.results[1].match_score == 75.0