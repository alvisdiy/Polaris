"""Scholarship version history — child of Scholarship (1:many, append-only)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.scholarship import Scholarship


class ScholarshipVersion(Base, TimestampMixin):
    __tablename__ = "scholarship_version"

    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0)
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
        nullable=False,
        sort_order=1,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, sort_order=2)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, sort_order=3)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, sort_order=4)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True, sort_order=5)

    # Relationship
    scholarship: Mapped["Scholarship"] = relationship(
        back_populates="versions",
    )

    # M9.1 Phase 3. version_number is the ordering the audit trail is read by,
    # so it must be unique per scholarship. Declared here as well as in the
    # migration: `Base.metadata.create_all()` runs before migrations against
    # the development database, and a constraint that only existed in one of
    # the two would mean tests and production disagreed about the schema.
    #
    # ReviewService also locks the Scholarship row with SELECT ... FOR UPDATE
    # before allocating, which is what makes the common path allocate without
    # conflict. This constraint is the backstop for writers that are not
    # ReviewService — only the database can refuse those.
    __table_args__ = (
        UniqueConstraint(
            "scholarship_id",
            "version_number",
            name="uq_scholarship_version_number",
        ),
    )

    def __repr__(self) -> str:
        return f"<ScholarshipVersion v{self.version_number} for {self.scholarship_id}>"
