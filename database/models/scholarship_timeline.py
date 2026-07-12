"""Scholarship timeline — child of Scholarship (1:1)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.scholarship import Scholarship


class ScholarshipTimeline(Base, TimestampMixin):
    __tablename__ = "scholarship_timeline"

    timeline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0)
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        sort_order=1,
    )
    application_open: Mapped[date | None] = mapped_column(Date, nullable=True, sort_order=2)
    application_deadline: Mapped[date | None] = mapped_column(Date, nullable=True, sort_order=3)
    application_cycle: Mapped[str | None] = mapped_column(String(32), nullable=True, sort_order=4)
    interview_date: Mapped[date | None] = mapped_column(Date, nullable=True, sort_order=5)
    result_date: Mapped[date | None] = mapped_column(Date, nullable=True, sort_order=6)
    study_start: Mapped[date | None] = mapped_column(Date, nullable=True, sort_order=7)

    # Relationship
    scholarship: Mapped["Scholarship"] = relationship(
        back_populates="timeline",
    )

    def __repr__(self) -> str:
        return f"<ScholarshipTimeline {self.timeline_id}>"
