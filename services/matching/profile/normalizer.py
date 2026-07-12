"""Normalizes UserProfile inputs to canonical forms."""

from __future__ import annotations

from services.matching.models.profile import UserProfile

# Degree aliases → canonical form
_DEGREE_ALIASES: dict[str, str] = {
    "master": "Master",
    "masters": "Master",
    "master's": "Master",
    "m.sc.": "Master",
    "msc": "Master",
    "bachelor": "Bachelor",
    "bachelors": "Bachelor",
    "bachelor's": "Bachelor",
    "b.sc.": "Bachelor",
    "bsc": "Bachelor",
    "phd": "PhD",
    "ph.d": "PhD",
    "ph.d.": "PhD",
    "doctorate": "PhD",
    "exchange": "Exchange",
    "short course": "Short Course",
    "shortcourse": "Short Course",
}

# Field of study aliases → canonical form
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
_EXPERIENCE_ALIASES: dict[str, str] = {
    "required": "Required",
    "mandatory": "Required",
    "preferred": "Preferred",
    "recommended": "Preferred",
    "optional": "Optional",
    "not required": "Not Required",
    "not_required": "Not Required",
    "none": "Not Required",
}

# Funding preference aliases → canonical form
_FUNDING_ALIASES: dict[str, str] = {
    "fully funded": "Fully Funded",
    "full": "Fully Funded",
    "full funding": "Fully Funded",
    "partial funded": "Partial Funded",
    "partial funding": "Partial Funded",
    "partial": "Partial Funded",
    "tuition only": "Tuition Only",
    "tuition-only": "Tuition Only",
    "tuition waiver": "Tuition Only",
}


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
        """Map degree aliases to canonical form."""
        canonical = _DEGREE_ALIASES.get(value.strip().lower())
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
