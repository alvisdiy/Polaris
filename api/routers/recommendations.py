"""Recommendations router — POST /recommendations."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException

from api.schemas import (
    ErrorResponse,
    RecommendationListResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from database.session import SessionLocal
from services.matching.explanation import ExplanationEngine
from services.matching.models.profile import UserProfile
from services.matching.orchestrator import ScholarshipIntelligenceEngine
from services.matching.profile import ProfileNormalizer, ProfileValidator
from services.scholarship import ScholarshipRepository

logger = logging.getLogger("polaris.api.recommendations")

router = APIRouter()

# Shared instances (stateless, safe to reuse)
_validator = ProfileValidator()
_normalizer = ProfileNormalizer()
_engine = ScholarshipIntelligenceEngine()
_explanation = ExplanationEngine()


@router.post(
    "/recommendations",
    response_model=RecommendationListResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Validation Error"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
    summary="Get scholarship recommendations",
    description=(
        "Run the deterministic matching pipeline against the student profile "
        "and return ranked scholarship recommendations. "
        "The pipeline: Validate → Normalize → Filter → Score → Rank → Explain."
    ),
)
def get_recommendations(request: RecommendationRequest):
    """Get ranked scholarship recommendations for a student profile.

    The matching engine evaluates all approved scholarships against the
    provided profile using weighted criteria (country, degree, field of study,
    GPA, language, funding, research, work, leadership).

    Returns top-10 recommendations sorted by match score.
    """
    start_time = time.perf_counter()
    logger.info("POST /recommendations — request received")

    try:
        # 1. Build and validate profile
        profile = UserProfile(
            target_country=request.target_country,
            degree=request.degree,
            field_of_study=request.field_of_study,
            current_gpa=request.current_gpa,
            ielts_score=request.ielts_score,
            toefl_score=request.toefl_score,
            research_experience=request.research_experience,
            work_experience=request.work_experience,
            publication=request.publication,
            leadership=request.leadership,
            funding_preference=request.funding_preference,
        )

        errors = _validator.validate(profile)
        if errors:
            logger.warning("Validation failed: %s", errors)
            raise HTTPException(status_code=422, detail=errors)

        # 2. Normalize profile
        profile = _normalizer.normalize(profile)

        # 3. Load approved scholarships from repository
        session = SessionLocal()
        try:
            repo = ScholarshipRepository(session)
            scholarships = repo.get_all_approved()
        finally:
            session.close()

        logger.info("Loaded %d approved scholarships", len(scholarships))

        # 4. Run matching pipeline
        results = _engine.match(profile, scholarships)

        # 5. Build response
        response_results = []
        for result in results:
            scholarship = next(s for s in scholarships if str(s.scholarship_id) == result.scholarship_id)

            explanation = _explanation.explain(profile, scholarship, result.criteria_scores)

            response_results.append(
                RecommendationResponse(
                    scholarship_name=result.scholarship_name,
                    provider_name=scholarship.provider.provider_name if scholarship.provider else "",
                    country=scholarship.country.name if scholarship.country else "",
                    match_score=result.match_score,
                    recommendation_category=result.recommendation_category,
                    explanation=explanation.summary,
                    strengths=explanation.strengths,
                    gaps=explanation.gaps,
                    next_steps=explanation.next_steps,
                    official_url=result.official_url,
                )
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "POST /recommendations — %d results in %.1fms",
            len(response_results),
            elapsed_ms,
        )

        return RecommendationListResponse(
            results=response_results,
            total=len(response_results),
        )

    except HTTPException:
        raise
    except Exception:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.exception("POST /recommendations — error after %.1fms", elapsed_ms)
        raise HTTPException(status_code=500, detail="Internal server error")
