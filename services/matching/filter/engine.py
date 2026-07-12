"""FilterEngine — eliminates non-actionable scholarships before scoring."""

from __future__ import annotations

from datetime import date

from database.models.scholarship import Scholarship
from services.matching.models.profile import UserProfile


class FilterEngine:
    """Applies mandatory filters to eliminate non-actionable scholarships.

    Only deadline validity is a mandatory filter. User preferences
    (country, degree, field) are scoring criteria handled by ScoringEngine.
    """

    def filter(
        self,
        profile: UserProfile,
        scholarships: list[Scholarship],
    ) -> list[Scholarship]:
        """Return only non-expired scholarships.

        Args:
            profile: Normalized user profile (accepted for API consistency;
                not used in MVP but reserved for future mandatory filters
                such as age limit).
            scholarships: Approved scholarships from Repository.

        Returns:
            List of non-expired scholarships.
        """
        return [s for s in scholarships if self._not_expired(s)]

    @staticmethod
    def _not_expired(scholarship: Scholarship) -> bool:
        """Deadline must be NULL (open-ended) or in the future."""
        if scholarship.timeline is None:
            return True
        deadline = scholarship.timeline.application_deadline
        if deadline is None:
            return True
        return deadline >= date.today()
