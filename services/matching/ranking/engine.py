"""RankingEngine — sorts scored scholarships and returns Top-N recommendations."""

from __future__ import annotations

from datetime import date

from database.models.scholarship import Scholarship
from services.matching.models.result import CriteriaScores, MatchExplanation, MatchResult

# Funding type priority (lower = better)
_FUNDING_PRIORITY = {
    "Fully Funded": 0,
    "Partial Funded": 1,
    "Tuition Only": 2,
}

# Recommendation categories from matching-engine-design-specification.md
_CATEGORIES = [
    (90, "Excellent Match"),
    (80, "Strong Match"),
    (70, "Good Match"),
    (60, "Moderate Match"),
    (0, "Low Match"),
]

_DEFAULT_TOP_N = 10


class RankingEngine:
    """Sorts scored scholarships and produces Top-N MatchResults."""

    def __init__(self, top_n: int = _DEFAULT_TOP_N):
        self._top_n = top_n

    def rank(
        self,
        scored: list[tuple[Scholarship, CriteriaScores]],
    ) -> list[MatchResult]:
        """Sort by score (desc), apply tiebreakers, return Top-N MatchResults.

        Sort keys:
        1. Total score (descending)
        2. Deadline (nearest first, NULL last)
        3. Funding type (Fully Funded > Partial > Tuition Only)
        4. Data completeness (more non-null fields = higher)

        Args:
            scored: List of (Scholarship, CriteriaScores) tuples.

        Returns:
            Top-N MatchResults sorted by rank.
        """
        sorted_scored = sorted(
            scored,
            key=lambda item: self._sort_key(item[0], item[1]),
            reverse=True,
        )

        results = []
        for scholarship, scores in sorted_scored[: self._top_n]:
            results.append(_to_match_result(scholarship, scores))
        return results

    @staticmethod
    def _sort_key(scholarship: Scholarship, scores: CriteriaScores) -> tuple[float, float, float, float, str]:
        """Build sort key: (score, deadline, funding, completeness, id).

        Deadline: nearest deadline = largest key value (sorts first with reverse=True).
        NULL deadlines get key=0 and sort last.

        The final scholarship_id component makes the order total: without it,
        rows tying on all four semantic keys flip position between queries
        (observed live with the 19-scholarship reference seed), which breaks
        the deterministic-repeated-request contract of the matching API.
        """
        # 1. Score (primary)
        total = scores.total

        # 2. Deadline (secondary — nearest first, NULL last)
        deadline = date.max
        if scholarship.timeline and scholarship.timeline.application_deadline:
            deadline = scholarship.timeline.application_deadline
        days_until = (deadline - date.today()).days
        max_days = 365 * 10
        deadline_key = max_days - days_until if days_until >= 0 else 0

        # 3. Funding type (tertiary)
        funding_key = 3 - _FUNDING_PRIORITY.get(scholarship.funding_type, 3)

        # 4. Data completeness (quaternary)
        completeness = _data_completeness(scholarship)

        # 5. Stable identity tiebreaker (arbitrary but deterministic order)
        return (total, deadline_key, funding_key, completeness, str(scholarship.scholarship_id))


def _data_completeness(scholarship: Scholarship) -> float:
    """Count non-null fields across scholarship and children as a fraction."""
    fields = [
        scholarship.scholarship_name,
        scholarship.degree,
        scholarship.funding_type,
        scholarship.field_of_study,
        scholarship.official_page_url,
    ]
    filled = sum(1 for f in fields if f)

    if scholarship.requirement:
        req = scholarship.requirement
        req_fields = [
            req.minimum_gpa,
            req.minimum_ielts,
            req.minimum_toefl,
            req.work_experience,
            req.research_experience,
            req.publication,
        ]
        filled += sum(1 for f in req_fields if f is not None)
        fields.extend(req_fields)

    if scholarship.benefit:
        ben = scholarship.benefit
        ben_fields = [
            ben.tuition_fee,
            ben.monthly_allowance,
            ben.accommodation,
            ben.health_insurance,
            ben.travel_ticket,
            ben.research_grant,
        ]
        filled += sum(1 for f in ben_fields if f)
        fields.extend(ben_fields)

    if scholarship.timeline:
        tl = scholarship.timeline
        tl_fields = [
            tl.application_open,
            tl.application_deadline,
            tl.interview_date,
            tl.result_date,
            tl.study_start,
        ]
        filled += sum(1 for f in tl_fields if f is not None)
        fields.extend(tl_fields)

    total = len(fields)
    return filled / total if total > 0 else 0.0


def _recommendation_category(score: float) -> str:
    """Map score to recommendation category."""
    for threshold, category in _CATEGORIES:
        if score >= threshold:
            return category
    return "Low Match"


def _to_match_result(scholarship: Scholarship, scores: CriteriaScores) -> MatchResult:
    """Convert a scored scholarship to a MatchResult."""
    url = scholarship.official_page_url or ""
    if scholarship.application_url:
        url = scholarship.application_url

    return MatchResult(
        scholarship_id=str(scholarship.scholarship_id),
        scholarship_name=scholarship.scholarship_name,
        match_score=scores.total,
        recommendation_category=_recommendation_category(scores.total),
        criteria_scores=scores,
        explanation=MatchExplanation(summary=""),
        official_url=url,
    )
