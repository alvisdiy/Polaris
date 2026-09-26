"""ScoringEngine — deterministic weighted scoring for scholarship matching."""

from __future__ import annotations

from database.models.scholarship import Scholarship
from services.matching.models.profile import UserProfile
from services.matching.models.result import CriteriaScores, CriterionResult
from services.matching.scoring.criteria import DEFAULT_WEIGHTS, CriteriaWeights

# Experience levels — ordinal scale for comparison
_EXPERIENCE_ORDINAL = {
    "Not Required": 0,
    "Optional": 1,
    "Preferred": 2,
    "Required": 3,
}


class ScoringEngine:
    """Calculates weighted match scores between a user profile and scholarships.

    Each criterion produces a CriterionResult with score, match status,
    and a human-readable reason. The total score is the sum of all
    partial scores (0–100).
    """

    def __init__(self, weights: CriteriaWeights | None = None):
        self._w = weights or DEFAULT_WEIGHTS

    def score(self, profile: UserProfile, scholarship: Scholarship) -> CriteriaScores:
        """Calculate match score for a single scholarship against a user profile.

        Args:
            profile: Normalized user profile.
            scholarship: Scholarship with eager-loaded requirement, benefit, timeline.

        Returns:
            CriteriaScores with individual scores, total, and details.
        """
        req = scholarship.requirement

        country = self._score_country(profile, scholarship)
        degree = self._score_degree(profile, scholarship)
        field = self._score_field(profile, scholarship)
        gpa = self._score_gpa(profile, req)
        language = self._score_language(profile, req)
        funding = self._score_funding(profile, scholarship)
        research = self._score_research(profile, req)
        work = self._score_work(profile, req)
        leadership = self._score_leadership(profile, req)

        results = [country, degree, field, gpa, language, funding, research, work, leadership]
        total = sum(r.score for r in results)

        return CriteriaScores(
            country=country.score,
            degree=degree.score,
            field_of_study=field.score,
            gpa=gpa.score,
            language=language.score,
            funding=funding.score,
            research=research.score,
            work=work.score,
            leadership=leadership.score,
            total=round(total, 2),
            details=results,
        )

    # ------------------------------------------------------------------
    # Individual criterion scorers
    # ------------------------------------------------------------------

    def _score_country(self, profile: UserProfile, scholarship: Scholarship) -> CriterionResult:
        """Country match — binary. Full weight if match."""
        w = self._w.country
        if scholarship.country and scholarship.country.name == profile.target_country:
            return CriterionResult(
                criterion="country", score=w, weight=w, matched=True,
                reason=f"Scholarship country '{profile.target_country}' matches target country.",
            )
        sch_country = scholarship.country.name if scholarship.country else "unspecified"
        return CriterionResult(
            criterion="country", score=0.0, weight=w, matched=False,
            reason=f"Scholarship country '{sch_country}' does not match target '{profile.target_country}'.",
        )

    def _score_degree(self, profile: UserProfile, scholarship: Scholarship) -> CriterionResult:
        """Degree match — binary. Full weight if match."""
        w = self._w.degree
        if scholarship.degree == profile.degree:
            return CriterionResult(
                criterion="degree", score=w, weight=w, matched=True,
                reason=f"Degree '{profile.degree}' matches scholarship requirement.",
            )
        return CriterionResult(
            criterion="degree", score=0.0, weight=w, matched=False,
            reason=f"Scholarship requires '{scholarship.degree}', user has '{profile.degree}'.",
        )

    def _score_field(self, profile: UserProfile, scholarship: Scholarship) -> CriterionResult:
        """Field of study overlap — proportional to overlap ratio.

        Score = (overlap_count / scholarship_field_count) * weight.
        If scholarship has no field restriction, full score.
        """
        w = self._w.field_of_study
        if not scholarship.field_of_study:
            return CriterionResult(
                criterion="field_of_study", score=w, weight=w, matched=True,
                reason="Scholarship has no field restriction — full score awarded.",
            )

        user_fields = {f.lower() for f in profile.field_of_study}
        sch_fields = {f.lower() for f in scholarship.field_of_study}
        overlap = user_fields & sch_fields

        if not overlap:
            return CriterionResult(
                criterion="field_of_study", score=0.0, weight=w, matched=False,
                reason=f"No overlap between user fields {sorted(user_fields)} and scholarship fields {sorted(sch_fields)}.",
            )

        ratio = len(overlap) / len(user_fields)
        sc = round(w * ratio, 2)
        matched = ratio >= 1.0
        return CriterionResult(
            criterion="field_of_study", score=sc, weight=w, matched=matched,
            reason=f"{len(overlap)}/{len(user_fields)} of user's field(s) supported ({', '.join(sorted(overlap))}).",
        )

    def _score_gpa(self, profile: UserProfile, req) -> CriterionResult:
        """GPA score — proportional to user_gpa / min_gpa, capped at weight.

        If no minimum requirement, full score.
        """
        w = self._w.gpa
        if req is None or req.minimum_gpa is None:
            return CriterionResult(
                criterion="gpa", score=w, weight=w, matched=True,
                reason="No minimum GPA requirement — full score awarded.",
            )
        if req.minimum_gpa <= 0:
            return CriterionResult(
                criterion="gpa", score=w, weight=w, matched=True,
                reason="Minimum GPA is zero — full score awarded.",
            )

        ratio = min(profile.current_gpa / req.minimum_gpa, 1.0)
        sc = round(w * ratio, 2)
        matched = profile.current_gpa >= req.minimum_gpa
        return CriterionResult(
            criterion="gpa", score=sc, weight=w, matched=matched,
            reason=f"User GPA {profile.current_gpa} vs minimum {req.minimum_gpa}.",
        )

    def _score_language(self, profile: UserProfile, req) -> CriterionResult:
        """Language score — based on IELTS or TOEFL against minimum.

        Uses whichever test is required. If neither required, full score.
        """
        w = self._w.language
        if req is None:
            return CriterionResult(
                criterion="language", score=w, weight=w, matched=True,
                reason="No language requirement — full score awarded.",
            )

        # IELTS path
        if req.ielts_required and req.minimum_ielts is not None:
            if profile.ielts_score is not None:
                ratio = min(profile.ielts_score / req.minimum_ielts, 1.0)
                sc = round(w * ratio, 2)
                matched = profile.ielts_score >= req.minimum_ielts
                return CriterionResult(
                    criterion="language", score=sc, weight=w, matched=matched,
                    reason=f"IELTS {profile.ielts_score} vs minimum {req.minimum_ielts}.",
                )
            return CriterionResult(
                criterion="language", score=0.0, weight=w, matched=False,
                reason="IELTS required but user has no IELTS score.",
            )

        # TOEFL path
        if req.toefl_required and req.minimum_toefl is not None:
            if profile.toefl_score is not None:
                ratio = min(profile.toefl_score / req.minimum_toefl, 1.0)
                sc = round(w * ratio, 2)
                matched = profile.toefl_score >= req.minimum_toefl
                return CriterionResult(
                    criterion="language", score=sc, weight=w, matched=matched,
                    reason=f"TOEFL {profile.toefl_score} vs minimum {req.minimum_toefl}.",
                )
            return CriterionResult(
                criterion="language", score=0.0, weight=w, matched=False,
                reason="TOEFL required but user has no TOEFL score.",
            )

        # No language requirement
        return CriterionResult(
            criterion="language", score=w, weight=w, matched=True,
            reason="No language requirement — full score awarded.",
        )

    def _score_funding(self, profile: UserProfile, scholarship: Scholarship) -> CriterionResult:
        """Funding preference match — binary. Full weight if match."""
        w = self._w.funding
        if scholarship.funding_type == profile.funding_preference:
            return CriterionResult(
                criterion="funding", score=w, weight=w, matched=True,
                reason=f"Funding type '{scholarship.funding_type}' matches preference.",
            )
        return CriterionResult(
            criterion="funding", score=0.0, weight=w, matched=False,
            reason=f"Funding type '{scholarship.funding_type}' does not match preference '{profile.funding_preference}'.",
        )

    def _score_research(self, profile: UserProfile, req) -> CriterionResult:
        """Research experience — ordinal comparison.

        Full score if user level >= requirement level.
        Half score if user is one level below.
        Zero otherwise.
        """
        w = self._w.research
        if req is None or req.research_experience is None:
            return CriterionResult(
                criterion="research", score=w, weight=w, matched=True,
                reason="No research requirement — full score awarded.",
            )

        user_level = _EXPERIENCE_ORDINAL.get(profile.research_experience, 0)
        req_level = _EXPERIENCE_ORDINAL.get(req.research_experience, 0)

        if user_level >= req_level:
            return CriterionResult(
                criterion="research", score=w, weight=w, matched=True,
                reason=f"Research '{profile.research_experience}' meets requirement '{req.research_experience}'.",
            )
        if user_level == req_level - 1:
            sc = round(w / 2, 2)
            return CriterionResult(
                criterion="research", score=sc, weight=w, matched=False,
                reason=f"Research '{profile.research_experience}' is one level below '{req.research_experience}' — partial score.",
            )
        return CriterionResult(
            criterion="research", score=0.0, weight=w, matched=False,
            reason=f"Research '{profile.research_experience}' is well below requirement '{req.research_experience}'.",
        )

    def _score_work(self, profile: UserProfile, req) -> CriterionResult:
        """Work experience — ordinal comparison (same logic as research)."""
        w = self._w.work
        if req is None or req.work_experience is None:
            return CriterionResult(
                criterion="work", score=w, weight=w, matched=True,
                reason="No work experience requirement — full score awarded.",
            )

        user_level = _EXPERIENCE_ORDINAL.get(profile.work_experience, 0)
        req_level = _EXPERIENCE_ORDINAL.get(req.work_experience, 0)

        if user_level >= req_level:
            return CriterionResult(
                criterion="work", score=w, weight=w, matched=True,
                reason=f"Work experience '{profile.work_experience}' meets requirement '{req.work_experience}'.",
            )
        if user_level == req_level - 1:
            sc = round(w / 2, 2)
            return CriterionResult(
                criterion="work", score=sc, weight=w, matched=False,
                reason=f"Work experience '{profile.work_experience}' is one level below '{req.work_experience}' — partial score.",
            )
        return CriterionResult(
            criterion="work", score=0.0, weight=w, matched=False,
            reason=f"Work experience '{profile.work_experience}' is well below requirement '{req.work_experience}'.",
        )

    def _score_leadership(self, profile: UserProfile, req) -> CriterionResult:
        """Leadership — binary. Full weight if user has leadership."""
        w = self._w.leadership
        if profile.leadership:
            return CriterionResult(
                criterion="leadership", score=w, weight=w, matched=True,
                reason="User has leadership experience.",
            )
        return CriterionResult(
            criterion="leadership", score=0.0, weight=w, matched=False,
            reason="User has no leadership experience.",
        )
