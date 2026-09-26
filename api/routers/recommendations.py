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
    ScholarshipDetailResponse,
    ScholarshipSummaryResponse,
    ScholarshipListResponse,
)
from database.session import SessionLocal
from services.matching.models.profile import UserProfile
from services.matching.service import MatchingService

logger = logging.getLogger("polaris.api.recommendations")

router = APIRouter()


def _build_profile(request: RecommendationRequest) -> UserProfile:
    """Build a UserProfile from the API request payload."""
    return UserProfile(
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
@router.post(
    "/api/v1/matching",
    response_model=RecommendationListResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Validation Error"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
    summary="Match a profile against scholarships",
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
        profile = _build_profile(request)

        session = SessionLocal()
        try:
            service = MatchingService(session)
            output = service.match(profile)
        finally:
            session.close()

        logger.info(
            "POST /recommendations — %d results in %.1fms",
            len(output.results),
            (time.perf_counter() - start_time) * 1000,
        )

        # Map application DTOs (MatchedScholarship) to API responses (RecommendationResponse)
        response_results = []
        for result in output.results:
            response_results.append(
                RecommendationResponse(
                    scholarship_id=result.scholarship_id,
                    scholarship_name=result.scholarship_name,
                    deadline=result.deadline,
                    provider_name=result.provider_name,
                    country=result.country,
                    match_score=result.match_score,
                    recommendation_category=result.recommendation_category,
                    explanation=result.summary,
                    strengths=result.strengths,
                    gaps=result.gaps,
                    next_steps=result.next_steps,
                    official_url=result.official_url,
                )
            )

        return RecommendationListResponse(
            results=response_results,
            total=len(response_results),
        )

    except ValueError as e:
        logger.warning("POST /recommendations — validation failed: %s", e)
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.exception("POST /recommendations — error after %.1fms", elapsed_ms)
        raise HTTPException(status_code=500, detail="Internal server error")