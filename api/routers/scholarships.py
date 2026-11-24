"""Scholarships router — list/search and detail endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    ScholarshipBenefitSchema,
    ScholarshipDetailResponse,
    ScholarshipListResponse,
    ScholarshipRequirementSchema,
    ScholarshipSummaryResponse,
    ScholarshipTimelineSchema,
)
from database.models.country import Country
from database.models.scholarship import Scholarship
from database.session import SessionLocal
from services.review.publication import public_filter
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
    funding: Optional[str] = Query(
        None, description="Filter by funding type (controlled vocabulary, e.g. 'Fully Funded')"
    ),
    sort: str = Query(
        "deadline",
        description="Sort order: 'deadline' closes soonest first (unknown deadlines last), 'name' is A-Z",
    ),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """List approved scholarships with optional filters and pagination."""
    if sort not in ("deadline", "name"):
        raise HTTPException(status_code=400, detail="sort must be 'deadline' or 'name'")
    session = SessionLocal()
    try:
        repo = ScholarshipRepository(session)
        scholarships, total = repo.search_approved(
            query=q, country=country, degree=degree, funding=funding, sort=sort,
            limit=limit, offset=offset,
        )
        results = [_to_summary(s) for s in scholarships]
        return ScholarshipListResponse(results=results, total=total)
    finally:
        session.close()


@router.get(
    "/countries",
    response_model=list[str],
    summary="Countries with at least one published scholarship",
)
def list_countries():
    """Country names the catalogue can actually return results for.

    The frontend filter dropdowns used to hardcode this list in two
    places, and the two copies disagreed (12 entries in Discover, 10 in
    the profile form — Brunei and Malaysia silently missing from one).
    The catalogue is the only honest source: a country with no published
    record is a filter that can only ever return an empty page.
    """
    session = SessionLocal()
    try:
        rows = (
            session.query(Country.name)
            .join(Scholarship, Scholarship.country_id == Country.country_id)
            .filter(public_filter())
            .distinct()
            .order_by(Country.name)
            .all()
        )
        return [name for (name,) in rows]
    finally:
        session.close()


@router.get(
    "/{scholarship_id}",
    response_model=ScholarshipDetailResponse,
    summary="Get scholarship detail",
    responses={404: {"description": "Scholarship not found"}},
)
def get_scholarship(scholarship_id: str):
    """Get full scholarship detail including requirements, benefits, timeline.

    Visibility is decided by the repository's canonical publication predicate,
    not here: an unpublished record is a 404 for the same reason a missing one
    is, and the rule that says so lives in one place.
    """
    # An id that is not a valid UUID would crash the query with a 500; a
    # missing record is a 404 concern, not a server error.
    try:
        uuid.UUID(scholarship_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Scholarship not found")
    session = SessionLocal()
    try:
        repo = ScholarshipRepository(session)
        sch = repo.get_published_by_id(scholarship_id)
        if not sch:
            raise HTTPException(status_code=404, detail="Scholarship not found")
        return _to_detail(sch)
    finally:
        session.close()


def _to_summary(sch) -> ScholarshipSummaryResponse:
    dl = sch.timeline.application_deadline if sch.timeline else None
    return ScholarshipSummaryResponse(
        scholarship_id=str(sch.scholarship_id),
        scholarship_name=sch.scholarship_name,
        # Null, never the string "Unknown". A placeholder that looks like a
        # value is how "Unknown Scholarship" and "Unknown" ended up as
        # identities in M8; the same mistake in a response body is the same
        # mistake with a JSON type on it.
        provider_name=sch.provider.provider_name if sch.provider else None,
        country=sch.country.name if sch.country else None,
        degree=sch.degree,
        degree_levels=[row.degree for row in (sch.degree_levels or [])],
        funding_type=sch.funding_type,
        field_of_study=sch.field_of_study or [],
        deadline=dl,
        last_verified_at=sch.last_verified_at,
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
        provider_name=sch.provider.provider_name if sch.provider else None,
        provider_type=sch.provider.provider_type if sch.provider else None,
        country=sch.country.name if sch.country else None,
        university=sch.university.name if sch.university else None,
        degree=sch.degree,
        degree_levels=[row.degree for row in (sch.degree_levels or [])],
        funding_type=sch.funding_type,
        field_of_study=sch.field_of_study or [],
        official_url=sch.official_page_url or "",
        application_url=sch.application_url,
        last_verified_at=sch.last_verified_at,
        requirement=req,
        benefit=ben,
        timeline=tl,
    )
