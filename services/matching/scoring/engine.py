"""ScoringEngine — deterministic weighted scoring for scholarship matching."""

from __future__ import annotations

from database.models.scholarship import Scholarship
from services.matching.models.profile import UserProfile
from services.matching.models.result import CriteriaScores
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

    Each criterion produces a partial score in [0, weight].
    The total score is the sum of all partial scores (0–100).
    """

    def __init__(self, weights: CriteriaWeights | None = None):
        self._w = weights or DEFAULT_WEIGHTS

    def score(self, profile: UserProfile, scholarship: Scholarship) -> CriteriaScores:
        """Calculate match score for a single scholarship against a user profile.

        Args:
            profile: Normalized user profile.
            scholarship: Scholarship with eager-loaded requirement, benefit, timeline.

        Returns:
            CriteriaScores with individual and total scores.
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

        total = country + degree + field + gpa + language + funding + research + work + leadership

        return CriteriaScores(
            country=country,
            degree=degree,
            field_of_study=field,
            gpa=gpa,
            language=language,
            funding=funding,
            research=research,
            work=work,
            leadership=leadership,
            total=round(total, 2),
        )

    # ------------------------------------------------------------------
    # Individual criterion scorers
    # ------------------------------------------------------------------

    def _score_country(self, profile: UserProfile, scholarship: Scholarship) -> float:
        """Country match — binary. Full weight if match."""
        if scholarship.country and scholarship.country.name == profile.target_country:
            return self._w.country
        return 0.0

    def _score_degree(self, profile: UserProfile, scholarship: Scholarship) -> float:
        """Degree match — binary. Full weight if match."""
        if scholarship.degree == profile.degree:
            return self._w.degree
        return 0.0

    def _score_field(self, profile: UserProfile, scholarship: Scholarship) -> float:
        """Field of study overlap — proportional to overlap ratio.

        Score = (overlap_count / scholarship_field_count) * weight.
        If scholarship has no field restriction, full score.
        """
        if not scholarship.field_of_study:
            return self._w.field_of_study

        user_fields = {f.lower() for f in profile.field_of_study}
        sch_fields = {f.lower() for f in scholarship.field_of_study}
        overlap = len(user_fields & sch_fields)
        if overlap == 0:
            return 0.0
        ratio = overlap / len(sch_fields)
        return round(self._w.field_of_study * ratio, 2)

    def _score_gpa(self, profile: UserProfile, req) -> float:
        """GPA score — proportional to user_gpa / min_gpa, capped at weight.

        If no minimum requirement, full score.
        """
        if req is None or req.minimum_gpa is None:
            return self._w.gpa
        if req.minimum_gpa <= 0:
            return self._w.gpa
        ratio = min(profile.current_gpa / req.minimum_gpa, 1.0)
        return round(self._w.gpa * ratio, 2)

    def _score_language(self, profile: UserProfile, req) -> float:
        """Language score — based on IELTS or TOEFL against minimum.

        Uses whichever test is required. If neither required, full score.
        """
        if req is None:
            return self._w.language

        # IELTS path
        if req.ielts_required and req.minimum_ielts is not None:
            if profile.ielts_score is not None:
                ratio = min(profile.ielts_score / req.minimum_ielts, 1.0)
                return round(self._w.language * ratio, 2)
            return 0.0  # Required but user has no score

        # TOEFL path
        if req.toefl_required and req.minimum_toefl is not None:
            if profile.toefl_score is not None:
                ratio = min(profile.toefl_score / req.minimum_toefl, 1.0)
                return round(self._w.language * ratio, 2)
            return 0.0

        # No language requirement
        return self._w.language

    def _score_funding(self, profile: UserProfile, scholarship: Scholarship) -> float:
        """Funding preference match — binary. Full weight if match."""
        if scholarship.funding_type == profile.funding_preference:
            return self._w.funding
        return 0.0

    def _score_research(self, profile: UserProfile, req) -> float:
        """Research experience — ordinal comparison.

        Full score if user level >= requirement level.
        Half score if user is one level below.
        Zero otherwise.
        """
        if req is None or req.research_experience is None:
            return self._w.research

        user_level = _EXPERIENCE_ORDINAL.get(profile.research_experience, 0)
        req_level = _EXPERIENCE_ORDINAL.get(req.research_experience, 0)

        if user_level >= req_level:
            return self._w.research
        if user_level == req_level - 1:
            return round(self._w.research / 2, 2)
        return 0.0

    def _score_work(self, profile: UserProfile, req) -> float:
        """Work experience — ordinal comparison (same logic as research)."""
        if req is None or req.work_experience is None:
            return self._w.work

        user_level = _EXPERIENCE_ORDINAL.get(profile.work_experience, 0)
        req_level = _EXPERIENCE_ORDINAL.get(req.work_experience, 0)

        if user_level >= req_level:
            return self._w.work
        if user_level == req_level - 1:
            return round(self._w.work / 2, 2)
        return 0.0

    def _score_leadership(self, profile: UserProfile, req) -> float:
        """Leadership — binary. Full weight if user has leadership."""
        # Scholarship requirement model doesn't have leadership field,
        # so this is purely based on user profile.
        if profile.leadership:
            return self._w.leadership
        return 0.0
