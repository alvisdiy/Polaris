"""Review / curation domain for Polaris.

Owns the publication boundary: `Scholarship.extraction_status` is written
here and nowhere else, every transition is audited, and publication is gated
on a deterministic quality report.

    PendingRecord ──▶ ReviewService.approve/reject/correct ──▶ ApprovedRecord

Nothing in the ingestion pipeline publishes. Nothing in the API publishes.
The matching engine and the public API read `extraction_status == approved`
through the repository, which is the single authoritative gate.
"""

from database.models.scholarship_candidate_revision import CandidateStatus

from .quality import (
    OPTIONAL_FIELDS,
    PLACEHOLDER_SOURCE_HOSTS,
    REQUIRED_TO_PUBLISH,
    FieldAssessment,
    FieldQuality,
    QualityReport,
    assess_benefits,
    assess_identity,
    assess_scalar,
    build_report,
    is_placeholder_source,
    placeholder_source_host,
)
from .service import (
    InvalidFieldValue,
    InvalidTransition,
    NotPublishable,
    ReviewOutcome,
    ReviewService,
    ReviewStatus,
    StaleCandidate,
)

__all__ = [
    "FieldAssessment",
    "FieldQuality",
    "QualityReport",
    "PLACEHOLDER_SOURCE_HOSTS",
    "REQUIRED_TO_PUBLISH",
    "OPTIONAL_FIELDS",
    "assess_benefits",
    "assess_identity",
    "assess_scalar",
    "build_report",
    "is_placeholder_source",
    "placeholder_source_host",
    "InvalidFieldValue",
    "InvalidTransition",
    "NotPublishable",
    "ReviewOutcome",
    "ReviewService",
    "ReviewStatus",
    "StaleCandidate",
    "CandidateStatus",
]
