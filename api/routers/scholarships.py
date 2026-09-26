"""Scholarships router — list/search and detail endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    ScholarshipDetailResponse,
    ScholarshipListResponse,
    ScholarshipRequirementSchema,
    ScholarshipBenefitSchema,
    ScholarshipTimelineSchema,
    ScholarshipSummaryResponse,
)
from database.session import SessionLocal
from services.scholarship.repository import ScholarshipRepository

logger = logging.getLogger("polaris.api.scholarships")

router = APIRouter(prefix="/api/v1/scholarships", tags=["scholarships"])


@router.get(
    "",
    response_model=ScholarshipListResponse,
    summary="List and search approved scholarships",
)
def list_scholarships(
    q: Optional[str] = Query(None, description="Search scholarship name"),
    country: Optional[str] = Query(None, description="Filter by country name or ISO3 code"),
    degree: Optional[str] = Query(None, description="Filter by degree level"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """List approved scholarships with optional filters and pagination."""
    session = SessionLocal()
    try:
        repo = ScholarshipRepository(session)
        scholarships, total = repo.search_approved(
            query=q, country=country, degree=degree,
            limit=limit, offset=offset,
        )
        results = [_to_summary(s) for s in scholarships]
        return ScholarshipListResponse(results=results, total=total)
    finally:
        session.close()


@router.get(
    "/{scholarship_id}",
    response_model=ScholarshipDetailResponse,
    summary="Get scholarship detail",
    responses={404: {"description": "Scholarship not found"}},
)
def get_scholarship(scholarship_id: str):
    """Get full scholarship detail including requirements, benefits, timeline."""
    session = SessionLocal()
    try:
        repo = ScholarshipRepository(session)
        sch = repo.get_by_id(scholarship_id)
        if not sch or sch.extraction_status != "approved":
            raise HTTPException(status_code=404, detail="Scholarship not found")
        return _to_detail(sch)
    finally:
        session.close()


def _to_summary(sch) -> ScholarshipSummaryResponse:
    dl = sch.timeline.application_deadline if sch.timeline else None
    return ScholarshipSummaryResponse(
        scholarship_id=str(sch.scholarship_id),
        scholarship_name=sch.scholarship_name,
        provider_name=sch.provider.provider_name if sch.provider else "Unknown",
        country=sch.country.name if sch.country else "Unknown",
        degree=sch.degree,
        funding_type=sch.funding_type,
        field_of_study=sch.field_of_study or [],
        deadline=dl,
        official_url=sch.official_page_url or "",
    )


def _to_detail(sch) -> ScholarshipDetailResponse:
    req = None
    if sch.requirement:
        req = ScholarshipRequirementSchema.model_validate(sch.requirement)
    ben = None
    if sch.benefit:
        ben = ScholarshipBenefitSchema.model_validate(sch.benefit)
    tl = None
    if sch.timeline:
        tl = ScholarshipTimelineSchema.model_validate(sch.timeline)

    return ScholarshipDetailResponse(
        scholarship_id=str(sch.scholarship_id),
        scholarship_name=sch.scholarship_name,
        provider_name=sch.provider.provider_name if sch.provider else "Unknown",
        provider_type=sch.provider.provider_type if sch.provider else None,
        country=sch.country.name if sch.country else "Unknown",
        degree=sch.degree,
        funding_type=sch.funding_type,
        field_of_study=sch.field_of_study or [],
        official_url=sch.official_page_url or "",
        application_url=sch.application_url,
        requirement=req,
        benefit=ben,
        timeline=tl,
    )
