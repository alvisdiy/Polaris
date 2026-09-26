"""MatchingService — application service that orchestrates the scholarship matching pipeline.

This is the single entry point for the matching pipeline.
It handles profile validation, normalization, data loading, and pipeline execution.
No business logic is duplicated — all heavy lifting is delegated to domain services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from services.matching.models.profile import UserProfile
from services.matching.orchestrator import ScholarshipIntelligenceEngine
from services.matching.profile import ProfileNormalizer, ProfileValidator
from services.scholarship import ScholarshipRepository


@dataclass(frozen=True)
class MatchedScholarship:
    """Output DTO of the Match Scholarship use case.

    Represents a scholarship matched against a student profile, enriched with
    all details required for presentation / API response.
    """

    scholarship_id: str
    scholarship_name: str
    deadline: date | None
    provider_name: str
    country: str
    match_score: float
    recommendation_category: str
    summary: str
    strengths: list[str]
    gaps: list[str]
    next_steps: list[str]
    official_url: str


@dataclass(frozen=True)
class MatchingOutput:
    """Output container for the matching service, containing results and stats."""

    results: list[MatchedScholarship]
    total_filtered: int


class MatchingService:
    """Application service orchestrating the full scholarship matching pipeline.

    Handles:
    - Profile validation and normalization
    - Data loading from repository
    - Pipeline execution (Filter → Score → Rank → Explain)
    - Result assembly and DTO mapping

    Does NOT contain business logic — delegates to domain services.
    """

    def __init__(
        self,
        session: Session,
        engine: ScholarshipIntelligenceEngine | None = None,
        validator: ProfileValidator | None = None,
        normalizer: ProfileNormalizer | None = None,
        repository: ScholarshipRepository | None = None,
    ) -> None:
        self._session = session
        self._engine = engine or ScholarshipIntelligenceEngine()
        self._validator = validator or ProfileValidator()
        self._normalizer = normalizer or ProfileNormalizer()
        self._repository = repository or ScholarshipRepository(session)

    def match(self, profile: UserProfile) -> MatchingOutput:
        """Run the full matching pipeline for a user profile.

        Args:
            profile: Raw user profile from the API layer.

        Returns:
            MatchingOutput with ranked MatchedScholarship DTOs and pipeline stats.

        Raises:
            ValueError: If the profile fails validation.
        """
        # 1. Validate raw profile
        errors = self._validator.validate(profile)
        if errors:
            raise ValueError(f"Profile validation failed: {errors}")

        # 2. Normalize to canonical forms
        normalized = self._normalizer.normalize(profile)

        # 3. Load approved scholarships
        scholarships = self._repository.get_all_approved()
        total_loaded = len(scholarships)

        # 4. Run the matching pipeline
        results = self._engine.match(normalized, scholarships)

        # 5. Map to application DTOs (MatchedScholarship)
        matched_scholarships = []
        for result in results:
            # Find the original scholarship to pull provider/country details
            scholarship = next(s for s in scholarships if str(s.scholarship_id) == result.scholarship_id)

            matched_scholarships.append(
                MatchedScholarship(
                    scholarship_id=result.scholarship_id,
                    scholarship_name=result.scholarship_name,
                    deadline=(
                        scholarship.timeline.application_deadline
                        if scholarship.timeline
                        else None
                    ),
                    provider_name=scholarship.provider.provider_name if scholarship.provider else "",
                    country=scholarship.country.name if scholarship.country else "",
                    match_score=result.match_score,
                    recommendation_category=result.recommendation_category,
                    summary=result.explanation.summary,
                    strengths=result.explanation.strengths,
                    gaps=result.explanation.gaps,
                    next_steps=result.explanation.next_steps,
                    official_url=result.official_url,
                )
            )

        return MatchingOutput(
            results=matched_scholarships,
            total_filtered=total_loaded - len(results),
        )

    @property
    def session(self) -> Session:
        """Database session used by this service instance."""
        return self._session
