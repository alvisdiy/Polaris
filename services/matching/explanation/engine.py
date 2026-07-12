"""ExplanationEngine — generates human-readable explanations for match results."""

from __future__ import annotations

from database.models.scholarship import Scholarship
from services.matching.models.profile import UserProfile
from services.matching.models.result import CriteriaScores, Explanation

# Thresholds for strength/gap classification
_STRONG_THRESHOLD = 0.8  # 80% of max weight = strength
_GAP_THRESHOLD = 0.5  # Below 50% of max weight = gap


class ExplanationEngine:
    """Generates deterministic, score-based explanations for match results.

    Does not use LLM. Produces structured Explanation objects from
    CriteriaScores and scholarship data.
    """

    def explain(
        self,
        profile: UserProfile,
        scholarship: Scholarship,
        scores: CriteriaScores,
    ) -> Explanation:
        """Generate explanation for a single match result.

        Args:
            profile: Normalized user profile.
            scholarship: Scholarship with eager-loaded children.
            scores: CriteriaScores from ScoringEngine.

        Returns:
            Explanation with summary, strengths, gaps, and next steps.
        """
        strengths = self._identify_strengths(scores)
        gaps = self._identify_gaps(profile, scholarship, scores)
        next_steps = self._suggest_next_steps(profile, scholarship, gaps)
        summary = self._build_summary(scores, strengths, gaps)

        return Explanation(
            summary=summary,
            strengths=strengths,
            gaps=gaps,
            next_steps=next_steps,
        )

    def _identify_strengths(self, scores: CriteriaScores) -> list[str]:
        """Identify criteria where the user scores well."""
        strengths = []
        checks = [
            (scores.country, 20, "Country matches target"),
            (scores.degree, 20, "Degree matches target"),
            (scores.field_of_study, 20, "Field of study overlap"),
            (scores.gpa, 15, "GPA meets minimum requirement"),
            (scores.language, 10, "Language score meets requirement"),
            (scores.funding, 5, "Funding preference matches"),
            (scores.research, 5, "Research experience meets requirement"),
            (scores.work, 3, "Work experience meets requirement"),
            (scores.leadership, 2, "Leadership experience"),
        ]
        for score, max_score, description in checks:
            if score >= max_score * _STRONG_THRESHOLD:
                strengths.append(description)
        return strengths

    def _identify_gaps(
        self,
        profile: UserProfile,
        scholarship: Scholarship,
        scores: CriteriaScores,
    ) -> list[str]:
        """Identify criteria where the user falls short."""
        gaps = []
        checks = [
            (scores.country, 20, "Country does not match target"),
            (scores.degree, 20, "Degree does not match target"),
            (scores.field_of_study, 20, "Limited field of study overlap"),
            (scores.gpa, 15, "GPA below minimum requirement"),
            (scores.language, 10, "Language score below requirement"),
            (scores.funding, 5, "Funding preference does not match"),
            (scores.research, 5, "Research experience below requirement"),
            (scores.work, 3, "Work experience below requirement"),
        ]
        for score, max_score, description in checks:
            if 0 < score < max_score * _GAP_THRESHOLD:
                gaps.append(description)
            elif score == 0 and max_score >= 10:
                # Zero on high-weight criteria is a significant gap
                gaps.append(description)
        return gaps

    def _suggest_next_steps(
        self,
        profile: UserProfile,
        scholarship: Scholarship,
        gaps: list[str],
    ) -> list[str]:
        """Suggest actionable next steps based on gaps."""
        steps = []

        for gap in gaps:
            if "GPA" in gap:
                steps.append("Consider improving your GPA or looking for scholarships with lower GPA requirements.")
            elif "Language" in gap:
                steps.append("Consider retaking IELTS/TOEFL to meet the minimum score requirement.")
            elif "Country" in gap:
                steps.append(
                    "This scholarship is in a different country than your target. "
                    "Consider if you're open to studying there."
                )
            elif "Degree" in gap:
                steps.append("This scholarship is for a different degree level. Verify eligibility requirements.")
            elif "Field" in gap:
                steps.append(
                    "This scholarship has limited overlap with your field of study. "
                    "Review the specific program requirements."
                )
            elif "Research" in gap:
                steps.append("Consider gaining research experience to strengthen your application.")
            elif "Work" in gap:
                steps.append("Consider gaining relevant work experience to strengthen your application.")

        # Always suggest visiting the official page
        if scholarship.application_url:
            steps.append(f"Visit the official application page: {scholarship.application_url}")
        elif scholarship.official_page_url:
            steps.append(f"Visit the official scholarship page: {scholarship.official_page_url}")

        return steps

    def _build_summary(
        self,
        scores: CriteriaScores,
        strengths: list[str],
        gaps: list[str],
    ) -> str:
        """Build a one-line summary based on score and category."""
        total = scores.total
        if total >= 90:
            return f"Excellent match ({total}/100). You meet most requirements for this scholarship."
        elif total >= 80:
            return f"Strong match ({total}/100). You meet the core requirements with minor gaps."
        elif total >= 70:
            return f"Good match ({total}/100). You meet some requirements but have notable gaps."
        elif total >= 60:
            return f"Moderate match ({total}/100). You have partial alignment with this scholarship."
        else:
            return f"Low match ({total}/100). This scholarship has significant mismatches with your profile."
