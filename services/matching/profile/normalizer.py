"""Normalizes UserProfile inputs to canonical forms."""

from __future__ import annotations

from services.domain.vocabulary import DEGREE, EXPERIENCE, FUNDING_TYPE
from services.matching.models.profile import UserProfile

# Alias tables for degree, experience level and funding now live in
# services/domain/vocabulary.py, so the matching normalizer, the ingestion
# validator, the review boundary and the database constraint cannot disagree.
#
# Field of study is deliberately NOT in that module. It is an open taxonomy,
# not a controlled vocabulary: "Nursing" and "Architecture" are perfectly valid
# values that nobody has added to an enum yet, and an unknown major is
# title-cased and passed through rather than rejected. Treating it as a closed
# set would reject real scholarships every time a source mentioned a subject
# Polaris had not enumerated.
_FIELD_ALIASES: dict[str, str] = {
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "cs": "Computer Science",
    "computer science": "Computer Science",
    "cs/it": "Computer Science",
    "it": "Information Technology",
    "information technology": "Information Technology",
    "ee": "Electrical Engineering",
    "electrical engineering": "Electrical Engineering",
    "me": "Mechanical Engineering",
    "mechanical engineering": "Mechanical Engineering",
    "natural sciences": "Natural Sciences",
    "natural science": "Natural Sciences",
    "social sciences": "Social Sciences",
    "social science": "Social Sciences",
    "business": "Business",
    "mba": "Business",
    "economics": "Economics",
    "law": "Law",
    "medicine": "Medicine",
    "public health": "Public Health",
    "environmental science": "Environmental Science",
    "environmental studies": "Environmental Science",
}

# Experience level aliases → canonical form
_EXPERIENCE_ALIASES: dict[str, str] = EXPERIENCE.aliases

# Funding preference aliases → canonical form
_FUNDING_ALIASES: dict[str, str] = FUNDING_TYPE.aliases


class ProfileNormalizer:
    """Normalizes user profile inputs to canonical forms.

    Idempotent: normalizing a profile that is already normalized
    produces the same profile.
    """

    def normalize(self, profile: UserProfile) -> UserProfile:
        """Return a normalized copy of the profile.

        Args:
            profile: The user profile to normalize.

        Returns:
            A new UserProfile with normalized values.
        """
        return UserProfile(
            target_country=self._normalize_country(profile.target_country),
            degree=self._normalize_degree(profile.degree),
            field_of_study=[self._normalize_field(f) for f in profile.field_of_study],
            current_gpa=profile.current_gpa,
            ielts_score=profile.ielts_score,
            toefl_score=profile.toefl_score,
            research_experience=self._normalize_experience(profile.research_experience),
            work_experience=self._normalize_experience(profile.work_experience),
            publication=self._normalize_experience(profile.publication),
            leadership=profile.leadership,
            funding_preference=self._normalize_funding(profile.funding_preference),
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_country(value: str) -> str:
        """Strip whitespace. Title-case for display consistency."""
        return value.strip().title()

    @staticmethod
    def _normalize_degree(value: str) -> str:
        """Map degree aliases to canonical form.

        Falls back to the cleaned input when nothing matches, and validation
        then reports it. Normalising an unrecognised degree to Bachelor would
        make an invalid profile look valid (ADR-016).
        """
        canonical = DEGREE.normalize(value)
        return canonical if canonical is not None else value.strip()

    @staticmethod
    def _normalize_field(value: str) -> str:
        """Map field of study aliases to canonical form."""
        canonical = _FIELD_ALIASES.get(value.strip().lower())
        return canonical if canonical is not None else value.strip().title()

    @staticmethod
    def _normalize_experience(value: str) -> str:
        """Map experience level aliases to canonical form."""
        canonical = _EXPERIENCE_ALIASES.get(value.strip().lower())
        return canonical if canonical is not None else value.strip()

    @staticmethod
    def _normalize_funding(value: str) -> str:
        """Map funding preference aliases to canonical form."""
        canonical = _FUNDING_ALIASES.get(value.strip().lower())
        return canonical if canonical is not None else value.strip()
