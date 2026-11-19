"""Review / curation router — the internal admin surface for curation.

This router deliberately does no curation itself. It validates the request,
calls `ReviewService`, and maps domain outcomes onto HTTP status codes. Every
state transition, quality gate and audit row lives in the service, so the same
rules apply whether a reviewer arrives here, from the CLI, or from a future
authenticated surface.

Authentication is a bearer token at the router level (`api/auth.py`): every
route on this surface requires `POLARIS_ADMIN_TOKEN`, and an unset token
disables the surface (503) rather than opening it. The token identifies an
operator, not a person — the reviewer identity is still taken from the request
body and recorded as `actor`, which says who claimed to review, not who they
are.

Route naming follows the existing convention (`/api/v1/...`), with the review
surface namespaced under `/admin` so it can never be mistaken for public data.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import require_admin
from api.schemas import (
    CandidateDecisionRequest,
    ReviewApproveRequest,
    ReviewDecisionRequest,
    ReviewDetailResponse,
    ReviewListResponse,
    ReviewMetricsResponse,
    ReviewOutcomeResponse,
    ReviewPatchRequest,
)
from database.session import SessionLocal
from services.review import (
    InvalidFieldValue,
    InvalidTransition,
    NotPublishable,
    ReviewService,
    ReviewStatus,
    StaleCandidate,
)

logger = logging.getLogger("polaris.api.review")

router = APIRouter(
    prefix="/api/v1/admin/review",
    tags=["review"],
    # Every route on this router can publish or reject a record. The token is
    # required at the router, not per-endpoint, so a new endpoint cannot be
    # added without it by accident.
    dependencies=[Depends(require_admin)],
)


@router.get(
    "/aggregator-candidates",
    summary="Aggregator discovery observations awaiting a scholarship record",
)
def list_aggregator_candidates(
    candidate_state: str | None = Query("pending_review", description="Observation state, or 'all'"),
    limit: int = Query(50, ge=1, le=200),
):
    """Expose blocked/unresolved aggregator evidence to the internal reviewer."""
    session = SessionLocal()
    try:
        return {
            "results": ReviewService(session).aggregator_candidates(
                limit=limit, state=None if candidate_state in (None, "", "all") else candidate_state
            )
        }
    finally:
        session.close()


def _uuid_or_404(value: str, label: str = "scholarship") -> str:
    """Validate the id here so a malformed id is a client error, not a 500."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} {value!r} is not a valid id",
        )


def _domain_error(exc: Exception) -> HTTPException:
    """Translate a refused transition into the right status.

    A refused state transition is a conflict with current state (409), not a
    bad request (400): the same request would succeed once the record reached
    a state it can be reviewed from. A failed quality gate is a 422, because
    the request was well formed but the record is not publishable.
    """
    if isinstance(exc, (NotPublishable, InvalidFieldValue)):
        # 422: the request was well formed but the value is not one Polaris
        # accepts. A refused vocabulary value is the reviewer's own input being
        # wrong, not a conflict with the record's current state, so it must not
        # read as "reload and try again".
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/candidates",
    summary="Proposed revisions awaiting a decision",
)
def list_candidates(
    scholarship_id: str | None = Query(
        None, description="Scope to one scholarship. Omit for every proposal."
    ),
    candidate_status: str | None = Query(
        "pending", description="pending | approved | rejected | superseded, or 'all'"
    ),
    limit: int = Query(50, ge=1, le=200),
):
    """The re-acquisition review queue.

    Separate from the scholarship queue because these records are already
    published: what a reviewer is deciding here is whether an *update* is
    warranted, not whether the opportunity is publishable at all.
    """
    session = SessionLocal()
    try:
        rows = ReviewService(session).candidates(
            scholarship_id,
            status=None if candidate_status in (None, "", "all") else candidate_status,
        )
        return {
            "results": [
                {
                    "candidate_id": str(c.candidate_id),
                    "scholarship_id": str(c.scholarship_id),
                    "status": c.status,
                    "origin": c.origin,
                    "source_url": c.source_url,
                    "raw_document_id": (
                        str(c.raw_document_id) if c.raw_document_id else None
                    ),
                    "detected_at": c.detected_at,
                    "base_version_number": c.base_version_number,
                    "proposed_changes": c.proposed_changes or [],
                    "field_provenance": c.field_provenance or {},
                    "decided_at": c.decided_at,
                    "decided_by": c.decided_by,
                    "decision_reason": c.decision_reason,
                }
                for c in rows[:limit]
            ],
            "total": len(rows),
        }
    finally:
        session.close()


@router.post(
    "/candidates/{candidate_id}/approve",
    response_model=ReviewOutcomeResponse,
    summary="Publish a candidate's proposed changes",
)
def approve_candidate(candidate_id: str, body: CandidateDecisionRequest):
    """Apply a reviewed proposal to the published record.

    The scholarship stays APPROVED throughout: what changes is the data, and
    only because a reviewer said so. Returns 409 when the record moved since
    the proposal was made, so a reviewer is never asked to rubber-stamp a stale
    diff.
    """
    session = SessionLocal()
    try:
        outcome = ReviewService(session).approve_candidate(
            str(candidate_id),
            actor=body.actor,
            reason=body.reason,
            evidence_url=body.evidence_url,
        )
        session.commit()
        return outcome.to_dict()
    except (InvalidTransition, NotPublishable, StaleCandidate) as exc:
        session.rollback()
        raise _domain_error(exc)
    finally:
        session.close()


@router.post(
    "/candidates/{candidate_id}/reject",
    response_model=ReviewOutcomeResponse,
    summary="Refuse a proposal, leaving the published record unchanged",
)
def reject_candidate(candidate_id: str, body: CandidateDecisionRequest):
    """Close a proposal without touching the scholarship.

    The record stays published with its existing values. A reason is required:
    "the fresh values are wrong" is only auditable if somebody says why.
    """
    session = SessionLocal()
    try:
        outcome = ReviewService(session).reject_candidate(
            str(candidate_id),
            actor=body.actor,
            reason=body.reason,
        )
        session.commit()
        return outcome.to_dict()
    except (InvalidTransition, NotPublishable) as exc:
        session.rollback()
        raise _domain_error(exc)
    finally:
        session.close()


@router.get(
    "/scholarships",
    response_model=ReviewListResponse,
    summary="The review queue",
)
def list_for_review(
    state: str | None = Query(
        ReviewStatus.PENDING_REVIEW,
        description="Review state to list. Pass 'all' for every state.",
    ),
    origin: str | None = Query(
        None, description="Filter by provenance origin (exploration, seed_script, ...)"
    ),
    country_id: str | None = Query(None, description="Scope the queue to one country"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List records awaiting curation, with what would block publication."""
    session = SessionLocal()
    try:
        service = ReviewService(session)
        # "all" is a query-language convenience, not a stored state, so it is
        # translated here rather than special-cased in the service.
        wanted = None if state in (None, "", "all") else state
        if country_id:
            country_id = _uuid_or_404(country_id, "country")

        rows, total = service.list_for_review(
            state=wanted, origin=origin, country_id=country_id,
            limit=limit, offset=offset,
        )
        return {"results": [service.queue_summary(r) for r in rows], "total": total}
    finally:
        session.close()


@router.get(
    "/metrics",
    response_model=ReviewMetricsResponse,
    summary="Curation metrics, split by provenance origin",
)
def review_metrics(
    country_id: str | None = Query(None, description="Scope metrics to one country"),
):
    """Counts and rates that show whether curation is actually working.

    The origin breakdown is the reason this endpoint exists: without it, rows
    inserted by a seed script are indistinguishable from rows exploration
    discovered and a reviewer approved.
    """
    session = SessionLocal()
    try:
        if country_id:
            country_id = _uuid_or_404(country_id, "country")
        return ReviewService(session).metrics(country_id=country_id)
    finally:
        session.close()


@router.get(
    "/scholarships/{scholarship_id}",
    response_model=ReviewDetailResponse,
    summary="One record with full provenance and audit history",
)
def get_for_review(scholarship_id: str):
    """The reviewer packet: identity, eligibility, funding, timeline,
    per-field quality, provenance, source documents, audit history and versions."""
    sid = _uuid_or_404(scholarship_id)
    session = SessionLocal()
    try:
        packet = ReviewService(session).review_packet(sid)
        if packet is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"scholarship {scholarship_id} not found",
            )
        return packet
    finally:
        session.close()


@router.patch(
    "/scholarships/{scholarship_id}",
    response_model=ReviewOutcomeResponse,
    summary="Correct fields on a record",
)
def patch_scholarship(scholarship_id: str, body: ReviewPatchRequest):
    """Apply reviewer edits, preserving every previous value.

    Rejected with 422 for an unknown field rather than ignored, because a
    silently dropped correction is indistinguishable from a successful one.
    """
    sid = _uuid_or_404(scholarship_id)
    session = SessionLocal()
    try:
        outcome = ReviewService(session).correct(
            sid,
            actor=body.actor,
            changes=body.changes,
            reason=body.reason,
            evidence_url=body.evidence_url,
            requeue=body.requeue,
            unmapped_qualification=body.unmapped_qualification,
        )
        session.commit()
        return outcome.to_dict()
    except (InvalidTransition, NotPublishable, InvalidFieldValue) as exc:
        session.rollback()
        raise _domain_error(exc)
    finally:
        session.close()


@router.post(
    "/scholarships/{scholarship_id}/approve",
    response_model=ReviewOutcomeResponse,
    summary="Publish a record",
)
def approve(scholarship_id: str, body: ReviewApproveRequest):
    """Approve a record, publishing it to the public API and matching.

    Returns 422 when a publication gate blocks the record, and 409 when the
    record is in a state it cannot be approved from.
    """
    sid = _uuid_or_404(scholarship_id)
    session = SessionLocal()
    try:
        outcome = ReviewService(session).approve(
            sid,
            actor=body.actor,
            reason=body.reason,
            evidence_url=body.evidence_url,
            override_quality=body.override_quality,
        )
        session.commit()
        return outcome.to_dict()
    except (InvalidTransition, NotPublishable) as exc:
        session.rollback()
        raise _domain_error(exc)
    finally:
        session.close()


@router.post(
    "/scholarships/{scholarship_id}/reject",
    response_model=ReviewOutcomeResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a record from publication",
)
def reject(scholarship_id: str, body: ReviewDecisionRequest):
    """Reject a record. A reason is mandatory: rejections are the evidence
    that curation is a real decision rather than a formality."""
    sid = _uuid_or_404(scholarship_id)
    session = SessionLocal()
    try:
        outcome = ReviewService(session).reject(
            sid, actor=body.actor, reason=body.reason, evidence_url=body.evidence_url
        )
        session.commit()
        return outcome.to_dict()
    except (InvalidTransition, NotPublishable) as exc:
        session.rollback()
        raise _domain_error(exc)
    finally:
        session.close()


@router.post(
    "/scholarships/{scholarship_id}/request-correction",
    response_model=ReviewOutcomeResponse,
    summary="Send a record back for correction",
)
def request_correction(scholarship_id: str, body: ReviewDecisionRequest):
    """Mark a record as needing work without deciding its final state."""
    sid = _uuid_or_404(scholarship_id)
    session = SessionLocal()
    try:
        outcome = ReviewService(session).request_correction(
            sid, actor=body.actor, reason=body.reason, evidence_url=body.evidence_url
        )
        session.commit()
        return outcome.to_dict()
    except (InvalidTransition, NotPublishable) as exc:
        session.rollback()
        raise _domain_error(exc)
    finally:
        session.close()
