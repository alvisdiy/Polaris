"""Validates UserProfile input against business rules."""

from __future__ import annotations

from services.matching.models.profile import UserProfile

# Valid enum values from the Data Dictionary
VALID_DEGREES = {"Bachelor", "Master", "PhD", "Exchange", "Short Course"}
VALID_FUNDING_PREFERENCES = {"Fully Funded", "Partial Funded", "Tuition Only"}
VALID_EXPERIENCE_LEVELS = {"Required", "Preferred", "Optional", "Not Required"}


class ProfileValidator:
    """Validates a UserProfile and returns a list of error strings.

    Returns an empty list if the profile is valid.
    """

    def validate(self, profile: UserProfile) -> list[str]:
        """Validate profile fields against business rules.

        Args:
            profile: The user profile to validate.

        Returns:
            List of error messages. Empty if valid.
        """
        errors: list[str] = []

        # Degree
        if profile.degree not in VALID_DEGREES:
            errors.append(f"Invalid degree: '{profile.degree}'. Must be one of: {', '.join(sorted(VALID_DEGREES))}")

        # Funding preference
        if profile.funding_preference not in VALID_FUNDING_PREFERENCES:
            errors.append(
                f"Invalid funding_preference: '{profile.funding_preference}'. "
                f"Must be one of: {', '.join(sorted(VALID_FUNDING_PREFERENCES))}"
            )

        # Experience levels
        for field_name in ("research_experience", "work_experience", "publication"):
            value = getattr(profile, field_name)
            if value not in VALID_EXPERIENCE_LEVELS:
                errors.append(
                    f"Invalid {field_name}: '{value}'. Must be one of: {', '.join(sorted(VALID_EXPERIENCE_LEVELS))}"
                )

        # Country
        if not profile.target_country.strip():
            errors.append("target_country cannot be empty.")

        # Field of study
        if not profile.field_of_study:
            errors.append("field_of_study must contain at least one entry.")

        return errors
