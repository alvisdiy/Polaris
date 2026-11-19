"""Candidate revisions — proposed changes awaiting a review decision.

M9.1 Phase 2. A re-acquisition fetches the official page again and the
extractor may find values the published record does not have (a deadline that
moved, a cycle that rolled over, a degree that is now stated). The tempting
implementation is to write those values onto the Scholarship row, and that is
precisely the defect this table exists to prevent: it would mutate public data
with no state transition and no audit row.

So the observation is stored *here* instead, and the Scholarship row is not
touched at all. The published record stays visible and byte-identical while the
candidate waits, which is what lets a reviewer be the only party who decides
whether a published value changes.

    RawDocument ──► candidate_revision (status=pending)
                              │
        ┌─────────────────────┴─────────────────────┐
        │ reject                                   │ approve
        ▼                                           ▼
  candidate closed,                        ReviewService applies the changes
  Scholarship untouched                       in one transaction:
  (still visible)                             1 version + 1 review action
                                              Scholarship stays APPROVED

This is deliberately not modelled as a `ScholarshipVersion`. A version row is
published history: its existence asserts that a value *became* the public one.
A candidate asserts the opposite — that a value has been seen and has not been
accepted. Sharing the table would let a pending proposal inflate the version
history and misrepresent what users have seen.

Relationship to the existing audit axis:

    ScholarshipVersion        published data history  (version_number is real)
    ScholarshipReviewAction   decision history         (who decided, and why)
    ScholarshipCandidateRevision  proposal history     (seen, not yet decided)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.scholarship import Scholarship


class CandidateStatus:
    """Lifecycle of one proposed revision.

    ``pending`` is the only state a reviewer can act on. ``superseded`` marks a
    candidate overtaken by a newer observation of the same source, so an old
    page cannot be approved after a fresher one already replaced it.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"

    TERMINAL = (APPROVED, REJECTED, SUPERSEDED)


class ScholarshipCandidateRevision(Base, TimestampMixin):
    """One proposed change set against a published scholarship."""

    __tablename__ = "scholarship_candidate_revision"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
        nullable=False,
        comment="The canonical scholarship this proposes changes to",
    )

    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=CandidateStatus.PENDING,
        comment="pending | approved | rejected | superseded",
    )

    # --- Where the proposal came from ---
    # The capture layer, so a reviewer can re-read exactly what the source
    # said rather than trusting the extracted diff.
    raw_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_document.document_id", ondelete="SET NULL"),
        nullable=True,
        comment="RawDocument this proposal was extracted from",
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    origin: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="What produced the candidate: reacquisition (M9.1), later manual reconciles",
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # --- What it proposes ---
    proposed_changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="[{field, previous, new}] — observed values not yet published",
    )
    field_provenance: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Per-field evidence for the proposed values: {field: {source_url, document_id, ...}}",
    )
    quality_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Publication-gate result the proposal would produce, for the reviewer",
    )

    # --- Optimistic concurrency ---
    # Captured when the candidate is proposed. Approval re-reads the current
    # version number; a mismatch means the record moved after the reviewer
    # started looking at it, and approving would silently discard that work.
    base_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="ScholarshipVersion.version_number when this candidate was proposed",
    )

    # --- Decision ---
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    scholarship: Mapped["Scholarship"] = relationship(
        "Scholarship",
        back_populates="candidate_revisions",
    )

    __table_args__ = (
        # The reviewer queue reads "pending candidates for this scholarship".
        Index(
            "ix_candidate_revision_scholarship_status",
            "scholarship_id",
            "status",
        ),
        # One pending proposal per (scholarship, source_url). Repeated crawls of
        # an unchanged page must not pile up duplicate rows for a reviewer to
        # triage, and the constraint is what makes that true under concurrency
        # rather than merely under a read-then-write check.
        Index(
            "uq_candidate_revision_pending_source",
            "scholarship_id",
            "source_url",
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        ),
    )

    def is_actionable(self) -> bool:
        return self.status == CandidateStatus.PENDING

    @property
    def raw_document_id_str(self) -> str | None:
        """The document id as a string, for JSON provenance payloads."""
        return str(self.raw_document_id) if self.raw_document_id else None

    def __repr__(self) -> str:
        return (
            f"<ScholarshipCandidateRevision {self.status} "
            f"for {self.scholarship_id} ({len(self.proposed_changes or [])} change(s))>"
        )
