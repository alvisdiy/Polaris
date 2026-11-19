"""ExplanationEngine — generates human-readable explanations for match results."""

from __future__ import annotations

from database.models.scholarship import Scholarship
from services.matching.models.profile import UserProfile
from services.matching.models.result import CriteriaScores, MatchExplanation

# Threshold: score/weight ratio below this is a gap
_GAP_RATIO = 0.5


class ExplanationEngine:
    """Generates deterministic, score-based explanations for match results.

    Does not use LLM. Consumes CriterionResult details from ScoringEngine
    to produce structured Explanation objects. Never recalculates scores.
    """

    def explain(
        self,
        profile: UserProfile,
        scholarship: Scholarship,
        scores: CriteriaScores,
    ) -> MatchExplanation:
        """Generate explanation for a single match result.

        Args:
            profile: Normalized user profile.
            scholarship: Scholarship with eager-loaded children.
            scores: CriteriaScores from ScoringEngine (with details).

        Returns:
            Explanation with summary, strengths, gaps, and next steps.
        """
        strengths = self._identify_strengths(scores)
        gaps = self._identify_gaps(scores)
        next_steps = self._suggest_next_steps(scholarship, scores)
        summary = self._build_summary(scores)

        return MatchExplanation(
            summary=summary,
            strengths=strengths,
            gaps=gaps,
            next_steps=next_steps,
        )

    @staticmethod
    def _identify_strengths(scores: CriteriaScores) -> list[str]:
        """Identify criteria where the user scores well.

        Uses CriterionResult.matched as the canonical source — no
        hardcoded weights, no re-derivation of scoring logic.
        """
        return [d.reason for d in scores.details if d.matched]

    @staticmethod
    def _identify_gaps(scores: CriteriaScores) -> list[str]:
        """Identify criteria where the user falls short.

        Uses CriterionResult.matched as the canonical source.
        Only reports gaps where score < weight (i.e. not fully matched).
        """
        return [d.reason for d in scores.details if not d.matched]

    @staticmethod
    def _suggest_next_steps(
        scholarship: Scholarship,
        scores: CriteriaScores,
    ) -> list[str]:
        """Suggest actionable next steps based on gap criteria.

        Uses CriterionResult.criterion names — not fragile string matching.
        """
        _ADVICE = {
            "gpa": "Consider improving your GPA or looking for scholarships with lower GPA requirements.",
            "language": "Consider retaking IELTS/TOEFL to meet the minimum score requirement.",
            "country": (
                "This scholarship is in a different country than your target. "
                "Consider if you're open to studying there."
            ),
            "degree": "This scholarship is for a different degree level. Verify eligibility requirements.",
            "field_of_study": (
                "This scholarship has limited overlap with your field of study. "
                "Review the specific program requirements."
            ),
            "research": "Consider gaining research experience to strengthen your application.",
            "work": "Consider gaining relevant work experience to strengthen your application.",
        }

        steps = []
        for detail in scores.details:
            if not detail.matched and detail.criterion in _ADVICE:
                steps.append(_ADVICE[detail.criterion])

        # Always suggest visiting the official page
        if scholarship.application_url:
            steps.append(f"Visit the official application page: {scholarship.application_url}")
        elif scholarship.official_page_url:
            steps.append(f"Visit the official scholarship page: {scholarship.official_page_url}")

        return steps

    @staticmethod
    def _build_summary(scores: CriteriaScores) -> str:
        """Build a one-line summary based on score and category."""
        total = scores.total
        if total >= 90:
            return f"Excellent match ({total}/100). You meet most requirements for this scholarship."
        if total >= 80:
            return f"Strong match ({total}/100). You meet the core requirements with minor gaps."
        if total >= 70:
            return f"Good match ({total}/100). You meet some requirements but have notable gaps."
        if total >= 60:
            return f"Moderate match ({total}/100). You have partial alignment with this scholarship."
        return f"Low match ({total}/100). This scholarship has significant mismatches with your profile."
