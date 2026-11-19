"""Review audit trail — append-only record of every curation decision.

`ScholarshipVersion` answers "what did this field hold, and when did it
change?". It does not answer "who decided that, and why?". This table
answers the second question.

The two are deliberately separate axes, not duplicate systems:

  ScholarshipVersion        data history    (field values over time)
  ScholarshipReviewAction   decision history (reviewer actions and reasons)

A version row is written whenever a *value* changes. A review action is
written whenever a *decision* is made. One approve that also corrects a
deadline writes one of each, linked by `version_id`.

Rows are never updated or deleted; corrections append a new action.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.scholarship import Scholarship


class ReviewActionType:
    """The review decision vocabulary.

    Deliberately strings, matching `extraction_status`, so the audit trail
    never drifts from the state it is auditing.
    """

    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CORRECTION = "needs_correction"
    CORRECTED = "corrected"
    REVERTED = "reverted"

    # Candidate lifecycle (M9.1). These describe a *proposal*, never the
    # scholarship's own state, so they are recorded on the audit trail without
    # appearing in `extraction_status` and without moving the publication
    # boundary. Keeping them distinct from APPROVED/REJECTED is what lets the
    # audit answer "was this value published?" without ambiguity.
    CANDIDATE_PROPOSED = "candidate_proposed"
    CANDIDATE_APPROVED = "candidate_approved"
    CANDIDATE_REJECTED = "candidate_rejected"


class ReviewSource:
    """Where a review action came from.

    `admin_api` and `review_cli` are the two real entry points today.
    `system` exists so future automated policy changes (never automatic
    approval) can be attributed rather than appearing as anonymous edits.
    """

    ADMIN_API = "admin_api"
    REVIEW_CLI = "review_cli"
    SYSTEM = "system"


class ScholarshipReviewAction(Base, TimestampMixin):
    """One auditable curation decision on one scholarship."""

    __tablename__ = "scholarship_review_action"

    review_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="submitted | approved | rejected | needs_correction | corrected | reverted",
    )
    actor: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Reviewer identity as asserted by the caller. No auth yet (see M11).",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    previous_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    new_state: Mapped[str] = mapped_column(String(24), nullable=False)

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    field_changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="[{field, previous, new}] — values the reviewer corrected in this action",
    )
    evidence_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
        comment="Official page the reviewer consulted as justification, when applicable",
    )

    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship_candidate_revision.candidate_id", ondelete="SET NULL"),
        nullable=True,
        comment="CandidateRevision this action decided, when it decided a proposal",
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship_version.version_id", ondelete="SET NULL"),
        nullable=True,
        comment="ScholarshipVersion row produced by this action, when it changed data",
    )
    quality_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Publication-gate result at decision time, so a later schema change cannot rewrite history",
    )

    scholarship: Mapped["Scholarship"] = relationship(
        "Scholarship",
        back_populates="review_actions",
    )

    def __repr__(self) -> str:
        return (
            f"<ScholarshipReviewAction {self.action} "
            f"by={self.actor} at={self.occurred_at}>"
        )
