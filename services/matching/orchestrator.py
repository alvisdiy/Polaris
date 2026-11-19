"""ScholarshipIntelligenceEngine — orchestrates the full matching pipeline."""

from __future__ import annotations

from database.models.scholarship import Scholarship
from services.matching.explanation import ExplanationEngine
from services.matching.filter import FilterEngine
from services.matching.models.profile import UserProfile
from services.matching.models.result import MatchResult
from services.matching.ranking import RankingEngine
from services.matching.scoring import ScoringEngine


class ScholarshipIntelligenceEngine:
    """Orchestrates Filter → Score → Rank → Explain pipeline.

    This is the single entry point for the matching engine.
    It does not contain business logic — it delegates to each stage.
    """

    def __init__(
        self,
        filter_engine: FilterEngine | None = None,
        scoring_engine: ScoringEngine | None = None,
        ranking_engine: RankingEngine | None = None,
        explanation_engine: ExplanationEngine | None = None,
    ):
        self._filter = filter_engine or FilterEngine()
        self._scoring = scoring_engine or ScoringEngine()
        self._ranking = ranking_engine or RankingEngine()
        self._explanation = explanation_engine or ExplanationEngine()

    def match(
        self,
        profile: UserProfile,
        scholarships: list[Scholarship],
    ) -> list[MatchResult]:
        """Run the full matching pipeline.

        Args:
            profile: Normalized user profile.
            scholarships: Approved scholarships from Repository (eager-loaded).

        Returns:
            Top-N MatchResults with explanations, sorted by rank.
        """
        return self.match_with_total(profile, scholarships)[0]

    def match_with_total(
        self,
        profile: UserProfile,
        scholarships: list[Scholarship],
    ) -> tuple[list[MatchResult], int]:
        """Run the pipeline and also report how many candidates matched.

        ``total_filtered`` alone cannot answer "how many scholarships matched
        this profile?" — it is the difference between the approved set and the
        Top-N page, which conflates three different things.

        Returns:
            ``(top_n_results, total_matched)`` where ``total_matched`` counts
            every candidate that survived the expiry filter, before Top-N.
        """
        # L1: Filter — remove non-actionable (expired deadlines)
        filtered = self._filter.filter(profile, scholarships)

        # L2: Score — calculate weighted match scores
        scored = [(s, self._scoring.score(profile, s)) for s in filtered]

        # L3: Rank — sort by score, apply tiebreakers, Top-N
        ranked, total_matched = self._ranking.rank_with_total(scored)

        # L4: Explain — add explanations to each result
        explained = []
        for result in ranked:
            scholarship = next(s for s, _ in scored if str(s.scholarship_id) == result.scholarship_id)
            explanation = self._explanation.explain(profile, scholarship, result.criteria_scores)
            # MatchResult is frozen — create a new one with explanation data
            explained.append(
                MatchResult(
                    scholarship_id=result.scholarship_id,
                    scholarship_name=result.scholarship_name,
                    match_score=result.match_score,
                    recommendation_category=result.recommendation_category,
                    criteria_scores=result.criteria_scores,
                    explanation=explanation,
                    official_url=result.official_url,
                )
            )

        return explained, total_matched
