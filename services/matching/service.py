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
    provider_name: str | None
    country: str | None
    match_score: float
    recommendation_category: str
    summary: str
    strengths: list[str]
    gaps: list[str]
    next_steps: list[str]
    official_url: str


@dataclass(frozen=True)
class MatchingOutput:
    """Output container for the matching service, containing results and stats.

    ``total_matched`` is every approved, non-expired scholarship that matched
    the profile. ``len(results)`` is the Top-N page actually returned. The two
    are different whenever more than ``top_n`` scholarships match, and an API
    that reports the second as the first tells a client it has seen
    everything when it has not.

    ``total_filtered`` is the complement of ``total_matched`` within the loaded
    approved set — in practice the expired records the deadline filter removed,
    since country/degree/field are scored rather than filtered.
    """

    results: list[MatchedScholarship]
    total_filtered: int
    total_matched: int = 0


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
        results, total_matched = self._engine.match_with_total(normalized, scholarships)

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
                    provider_name=scholarship.provider.provider_name if scholarship.provider else None,
                    country=scholarship.country.name if scholarship.country else None,
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
            total_filtered=total_loaded - total_matched,
            total_matched=total_matched,
        )

    @property
    def session(self) -> Session:
        """Database session used by this service instance."""
        return self._session
