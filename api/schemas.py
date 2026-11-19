"""Request and response schemas for the Recommendation API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.domain.vocabulary import DEGREE, FUNDING_TYPE


class RecommendationRequest(BaseModel):
    """Student profile for scholarship matching.

    All fields represent the student's current academic status and preferences.
    The matching engine uses these to score and rank available scholarships.
    """

    target_country: str = Field(
        ...,
        description="Target country for study (e.g., 'Japan', 'Germany', 'South Korea').",
        examples=["Japan"],
    )
    degree: str = Field(
        ...,
        description=(
            "Target degree level. Valid: "
            f"{', '.join(DEGREE.order)}."
        ),
        examples=["Master"],
    )
    field_of_study: list[str] = Field(
        ...,
        min_length=1,
        description="List of fields of study. At least one required.",
        examples=[["Computer Science", "Artificial Intelligence"]],
    )
    current_gpa: float = Field(
        ...,
        ge=0.0,
        le=4.0,
        description="Current GPA on a 4.0 scale.",
        examples=[3.5],
    )
    ielts_score: float | None = Field(
        default=None,
        ge=0.0,
        le=9.0,
        description="IELTS score (0.0–9.0). Null if not taken.",
        examples=[7.0],
    )
    toefl_score: int | None = Field(
        default=None,
        ge=0,
        le=120,
        description="TOEFL iBT score (0–120). Null if not taken.",
        examples=[100],
    )
    research_experience: str = Field(
        ...,
        description="Research experience level. Valid: Not Required, Optional, Preferred, Required.",
        examples=["Preferred"],
    )
    work_experience: str = Field(
        ...,
        description="Work experience level. Valid: Not Required, Optional, Preferred, Required.",
        examples=["Optional"],
    )
    publication: str = Field(
        ...,
        description="Publication experience. Valid: Not Required, Optional, Preferred, Required.",
        examples=["Not Required"],
    )
    leadership: bool = Field(
        ...,
        description="Whether the student has leadership experience.",
        examples=[True],
    )
    funding_preference: str = Field(
        ...,
        description=(
            "Funding preference. Valid: "
            f"{', '.join(FUNDING_TYPE.order)}."
        ),
        examples=["Fully Funded"],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "target_country": "Japan",
                    "degree": "Master",
                    "field_of_study": ["Computer Science", "Artificial Intelligence"],
                    "current_gpa": 3.5,
                    "ielts_score": 7.0,
                    "toefl_score": None,
                    "research_experience": "Preferred",
                    "work_experience": "Optional",
                    "publication": "Not Required",
                    "leadership": True,
                    "funding_preference": "Fully Funded",
                }
            ]
        }
    }


class RecommendationResponse(BaseModel):
    """Single scholarship recommendation with match details."""

    scholarship_id: str = Field(
        ...,
        description="Stable scholarship identifier.",
    )
    scholarship_name: str = Field(
        ...,
        description="Official scholarship name.",
        examples=["MEXT Scholarship 2027"],
    )
    deadline: date | None = Field(
        None,
        description="Application deadline, or null when not published.",
    )
    provider_name: str | None = Field(
        None,
        description=(
            "Name of the scholarship provider organization. Null when the "
            "record has no provider resolved — never a placeholder string."
        ),
        examples=["Ministry of Education, Culture, Sports, Science and Technology"],
    )
    country: str | None = Field(
        None,
        description=(
            "Country where the scholarship is offered. Null when unresolved."
        ),
        examples=["Japan"],
    )
    match_score: float = Field(
        ...,
        description="Match score from 0 to 100.",
        examples=[92.5],
    )
    recommendation_category: str = Field(
        ...,
        description="Recommendation category based on score.",
        examples=["Excellent Match"],
    )
    explanation: str = Field(
        ...,
        description="Human-readable summary of the match quality.",
        examples=["Excellent match (92.5/100). You meet most requirements for this scholarship."],
    )
    strengths: list[str] = Field(
        ...,
        description="List of matching strengths.",
        examples=[["Country matches target", "Degree matches target", "GPA meets minimum requirement"]],
    )
    gaps: list[str] = Field(
        ...,
        description="List of identified gaps between profile and requirements.",
        examples=[["Limited field of study overlap"]],
    )
    next_steps: list[str] = Field(
        ...,
        description="Recommended next actions for the student.",
        examples=[["Visit the official application page: https://www.studyinjapan.go.jp/en/"]],
    )
    official_url: str = Field(
        ...,
        description="URL to the official scholarship page.",
        examples=["https://www.studyinjapan.go.jp/en/"],
    )


class RecommendationListResponse(BaseModel):
    """Response containing ranked scholarship recommendations.

    Two different numbers, deliberately named differently:

    * ``total``      — every approved, non-expired scholarship that matched
      the profile. This is the size of the result *set*.
    * ``returned``   — how many are in ``results``, which is capped at the
      engine's Top-N.

    A client that receives 10 of 20 must be able to tell. Reporting
    ``len(results)`` as ``total`` makes a truncated page look complete.
    """

    results: list[RecommendationResponse] = Field(
        ...,
        description="Ranked recommendations, sorted by match score descending.",
    )
    total: int = Field(
        ...,
        description="Total matching scholarships, before the Top-N cut.",
        examples=[37],
    )
    returned: int = Field(
        ...,
        description="Number of recommendations included in `results`.",
        examples=[10],
    )


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str | list[str] = Field(
        ...,
        description="Error message or list of validation errors.",
        examples=["Internal server error"],
    )


class ScholarshipRequirementSchema(BaseModel):
    minimum_gpa: float | None = None
    ielts_required: bool
    minimum_ielts: float | None = None
    toefl_required: bool
    minimum_toefl: int | None = None
    work_experience: str | None = None
    research_experience: str | None = None
    publication: str | None = None

    model_config = ConfigDict(from_attributes=True)

class ScholarshipBenefitSchema(BaseModel):
    tuition_fee: bool
    monthly_allowance: bool
    accommodation: bool
    health_insurance: bool
    travel_ticket: bool
    research_grant: bool

    model_config = ConfigDict(from_attributes=True)

class ScholarshipTimelineSchema(BaseModel):
    application_open: date | None = None
    application_deadline: date | None = None
    application_cycle: str | None = None
    interview_date: date | None = None
    result_date: date | None = None
    study_start: date | None = None

    model_config = ConfigDict(from_attributes=True)

class ScholarshipSummaryResponse(BaseModel):
    scholarship_id: str
    scholarship_name: str
    # Nullable, like the columns they come from. A record whose provider or
    # country was never resolved reports null; it does not report the string
    # "Unknown", which is a fabricated value wearing a data type.
    provider_name: str | None = None
    country: str | None = None
    # Nullable in the database and nullable here. Declaring these required
    # while the column allows NULL made the list endpoint return 500 for any
    # scholarship whose page did not state a degree or funding type, which is
    # ordinary and legitimate data.
    degree: str | None = None
    # The award's levels when its page stated several. ``degree`` stays the
    # single-value field; a record with a set has ``degree`` null and this
    # populated, which is how a multi-level programme stays filterable.
    degree_levels: list[str] = Field(default_factory=list)
    funding_type: str | None = None
    field_of_study: list[str] = Field(default_factory=list)
    deadline: date | None = None
    official_url: str

class ScholarshipListResponse(BaseModel):
    results: list[ScholarshipSummaryResponse]
    total: int

class ScholarshipDetailResponse(BaseModel):
    scholarship_id: str
    scholarship_name: str
    provider_name: str | None = None
    provider_type: str | None = None
    country: str | None = None
    # See ScholarshipSummaryResponse: nullable in the database, so nullable here.
    degree: str | None = None
    degree_levels: list[str] = Field(default_factory=list)
    funding_type: str | None = None
    field_of_study: list[str] = Field(default_factory=list)
    official_url: str
    application_url: str | None = None

    # Source trust, at V0.1 depth: when this record was last checked against
    # its official page. Full provenance stays on the reviewer surface; a
    # student needs to know the date, not the document id.
    last_verified_at: datetime | None = Field(
        None, description="When this record was last verified against its source."
    )

    requirement: ScholarshipRequirementSchema | None = None
    benefit: ScholarshipBenefitSchema | None = None
    timeline: ScholarshipTimelineSchema | None = None


# ---------------------------------------------------------------------------
# Review / curation (internal admin surface)
#
# Deliberately separate from the public scholarship schemas: a reviewer sees
# uncertainty, provenance and audit history that no public response exposes.
# ---------------------------------------------------------------------------


class ReviewIdentitySchema(BaseModel):
    """Who and what this record is, before any judgement about its quality."""

    scholarship_name: str
    provider_name: str | None = None
    provider_type: str | None = None
    country: str | None = None
    university: str | None = None
    official_url: str | None = None
    application_url: str | None = None
    source_id: str
    source_name: str | None = None
    source_official_url: str | None = None
    source_verification_state: str | None = None


class ReviewEligibilitySchema(BaseModel):
    degree: str | None = None
    funding_type: str | None = None
    field_of_study: list[str] = Field(default_factory=list)
    minimum_gpa: float | None = None
    ielts_required: bool | None = None
    minimum_ielts: float | None = None
    toefl_required: bool | None = None
    minimum_toefl: int | None = None
    work_experience: str | None = None
    research_experience: str | None = None
    publication: str | None = None


class ReviewFundingSchema(BaseModel):
    tuition_fee: bool | None = None
    monthly_allowance: bool | None = None
    accommodation: bool | None = None
    health_insurance: bool | None = None
    travel_ticket: bool | None = None
    research_grant: bool | None = None


class ReviewTimelineSchema(BaseModel):
    application_open: date | None = None
    application_deadline: date | None = None
    application_cycle: str | None = None
    interview_date: date | None = None
    result_date: date | None = None
    study_start: date | None = None


class FieldQualitySchema(BaseModel):
    """One field's publication verdict, and the evidence behind it."""

    field: str
    quality: str = Field(
        description=(
            "KNOWN | UNKNOWN | NOT_APPLICABLE | MISSING | CONFLICTING. "
            "UNKNOWN means the source was silent; MISSING means Polaris failed "
            "to retrieve the field. Only MISSING blocks publication."
        )
    )
    value: object | None = None
    detail: str = ""


class QualityReportSchema(BaseModel):
    publishable: bool
    blocking: list[str] = Field(default_factory=list)
    conflicting: list[str] = Field(default_factory=list)
    overridden_fields: list[str] = Field(default_factory=list)
    fields: dict[str, FieldQualitySchema] = Field(default_factory=dict)


class ProvenanceSchema(BaseModel):
    """Where the *currently published* value of one field came from.

    Every entry describes the value on the record now, not the one it used to
    hold. The previous entry is nested under ``previous`` so a superseded
    value stays recoverable from this entry alone; the full history is in the
    version and audit rows.
    """

    source_url: str | None = None
    document_id: str | None = None
    extracted_at: datetime | None = None
    confidence: float | None = None
    method: str | None = None

    # Who decided the current value, when a human did. Null for machine
    # extraction, which never has an actor.
    origin: str | None = Field(
        None, description="machine_extracted | human_review | reacquisition."
    )
    actor: str | None = Field(None, description="Reviewer who set this value.")
    corrected_at: datetime | None = None
    review_source: str | None = Field(
        None, description="Surface the correction was made from."
    )
    reason: str | None = Field(
        None, description="Why the reviewer made the change."
    )
    current_value: Any | None = Field(
        None, description="The published value this entry describes."
    )
    previous_value: Any | None = Field(
        None, description="The value this entry replaced."
    )
    evidence_url: str | None = Field(
        None, description="Page the reviewer consulted. Null when none was given."
    )

    # Normalization evidence: what the source actually said when it mapped to
    # a canonical value. Distinct from the human-correction keys above.
    source_value: str | None = None
    unmapped_qualification: str | None = Field(
        None,
        description=(
            "Source wording for a qualification Polaris has no category for, "
            "recorded against a null value rather than mapped."
        ),
    )
    note: str | None = None

    previous: dict | None = Field(
        None, description="The provenance this entry superseded."
    )


class DocumentReferenceSchema(BaseModel):
    document_id: str
    source_url: str
    fetched_at: datetime
    status_code: int | None = None
    content_type: str | None = None
    processing_status: str | None = None


class ReviewActionSchema(BaseModel):
    review_action_id: str
    action: str
    actor: str
    occurred_at: datetime
    previous_state: str | None = None
    new_state: str
    reason: str | None = None
    field_changes: list[dict] = Field(default_factory=list)
    evidence_url: str | None = None
    version_id: str | None = None


class VersionSchema(BaseModel):
    version_id: str
    version_number: int
    changed_at: datetime
    source_url: str | None = None
    change_summary: str | None = None


class CandidateRevisionSchema(BaseModel):
    """One proposed change set awaiting a review decision.

    Exists so a reviewer can see what an upstream re-crawl observed without the
    published record having changed. Nothing here is public: approving it is a
    separate, explicit action.
    """

    candidate_id: str
    status: str = Field(description="pending | approved | rejected | superseded")
    origin: str | None = None
    source_url: str | None = None
    raw_document_id: str | None = None
    detected_at: datetime
    base_version_number: int | None = None
    proposed_changes: list[dict] = Field(
        default_factory=list,
        description="[{field, previous, new}] — values seen upstream, not yet published",
    )
    field_provenance: dict[str, ProvenanceSchema] = Field(default_factory=dict)


class CandidateDecisionRequest(BaseModel):
    """Approve or reject a candidate. A reason is mandatory for both.

    Rejecting a candidate does not unpublish the scholarship: the opportunity
    stays public with the values it already had.
    """

    reason: str = Field(
        ...,
        min_length=1,
        description="Why this proposal is accepted or refused. Stored on the audit trail.",
        examples=["official page confirms the 2029 cycle"],
    )
    actor: str = Field(..., min_length=1, examples=["alice"])
    evidence_url: str | None = Field(
        None, description="Official page consulted as justification."
    )


class ReviewItemSummary(BaseModel):
    """Queue row: enough to triage without opening the whole record."""

    scholarship_id: str
    scholarship_name: str
    provider_name: str | None = None
    country: str | None = None
    official_url: str | None = None
    extraction_status: str
    provenance_origin: str | None = None
    extraction_confidence: float | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    blocking_fields: list[str] = Field(default_factory=list)
    conflicting_fields: list[str] = Field(default_factory=list)


class ReviewListResponse(BaseModel):
    results: list[ReviewItemSummary]
    total: int


class ReviewDetailResponse(BaseModel):
    scholarship_id: str
    extraction_status: str
    identity: ReviewIdentitySchema
    eligibility: ReviewEligibilitySchema
    funding: ReviewFundingSchema
    timeline: ReviewTimelineSchema
    quality: QualityReportSchema
    provenance_origin: str | None = None
    extraction_confidence: float | None = None
    conflicts: list[dict] = Field(default_factory=list)
    field_provenance: dict[str, ProvenanceSchema] = Field(default_factory=dict)
    source_documents: list[DocumentReferenceSchema] = Field(default_factory=list)
    history: list[ReviewActionSchema] = Field(default_factory=list)
    versions: list[VersionSchema] = Field(default_factory=list)
    pending_candidates: list[CandidateRevisionSchema] = Field(default_factory=list)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    review_notes: str | None = None


class ReviewPatchRequest(BaseModel):
    """A reviewer edit.

    The editable set is narrow on purpose. Correcting ``official_page_url`` or
    ``application_url`` is legitimate; re-pointing ``source_id`` would break the
    chain of custody, so it is simply not accepted.
    """

    changes: dict = Field(
        ...,
        description=(
            "Fields to correct. Editable: scholarship_name, provider_id, degree, "
            "funding_type, field_of_study, official_page_url, application_url, "
            "deadline, application_open, application_cycle, interview_date, "
            "result_date, study_start, minimum_gpa, ielts_required, minimum_ielts, "
            "toefl_required, minimum_toefl, work_experience, research_experience, "
            "publication, tuition_fee, monthly_allowance, accommodation, "
            "health_insurance, travel_ticket, research_grant."
        ),
        examples=[{"deadline": "2027-05-01", "funding_type": "Partial Funding"}],
    )
    reason: str = Field(
        ...,
        min_length=1,
        description="Why the change is correct. Stored on the audit trail.",
        examples=["official page updated the deadline to 1 May 2027"],
    )
    actor: str = Field(
        ...,
        min_length=1,
        description="Reviewer identity. Recorded on every action.",
        examples=["alice"],
    )
    evidence_url: str | None = Field(
        None, description="Official page consulted as justification."
    )
    requeue: bool = Field(
        True,
        description=(
            "Re-queue for a second look after correcting (the default), or keep "
            "the record's current state."
        ),
    )
    unmapped_qualification: dict[str, str] | None = Field(
        None,
        description=(
            "Field -> the source wording for a qualification Polaris has no "
            "category for, e.g. {\"degree\": \"diploma\"}. The field must be "
            "corrected to null in the same request; the wording is kept as "
            "evidence instead of being mapped to a degree level."
        ),
        examples=[{"degree": "diploma"}],
    )


class ReviewDecisionRequest(BaseModel):
    """Shared body for approve, reject and request-correction."""

    actor: str = Field(..., min_length=1, examples=["alice"])
    reason: str | None = Field(
        None, description="Why. Required to reject, and to override a gate."
    )
    evidence_url: str | None = None


class ReviewApproveRequest(ReviewDecisionRequest):
    override_quality: bool = Field(
        False,
        description=(
            "Publish despite a blocking gate. Requires a reason. Cannot "
            "override identity or provenance failures."
        ),
    )


class ReviewOutcomeResponse(BaseModel):
    scholarship_id: str
    previous_state: str
    new_state: str
    action: str
    version_id: str | None = None
    field_changes: list[dict] = Field(default_factory=list)
    quality_report: QualityReportSchema | None = None


class ReviewMetricsResponse(BaseModel):
    """Evidence that curation works, split by how each record arrived.

    Reporting totals without the origin breakdown is what would let manual
    seed scripts masquerade as a working discovery pipeline.
    """

    total: int
    by_state: dict[str, int]
    by_origin: dict[str, int]
    pending_review: int
    approved: int
    rejected: int
    needs_correction: int
    approval_rate: float | None = Field(
        None, description="approved / (approved + rejected); null when none decided"
    )
    rejection_rate: float | None = None
    undecided: int
    records_with_conflicts: int
    low_confidence_extractions: int = Field(
        0, description="Records the extractor itself judged below its accept threshold"
    )
