"""Scholarship eligibility requirements — child of Scholarship (1:1)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.scholarship import Scholarship


class ScholarshipRequirement(Base, TimestampMixin):
    __tablename__ = "scholarship_requirement"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0
    )
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        sort_order=1,
    )
    minimum_gpa: Mapped[float | None] = mapped_column(Float, nullable=True, sort_order=2)
    ielts_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=3)
    minimum_ielts: Mapped[float | None] = mapped_column(Float, nullable=True, sort_order=4)
    toefl_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=5)
    minimum_toefl: Mapped[int | None] = mapped_column(Integer, nullable=True, sort_order=6)
    gre_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=7)
    age_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, sort_order=8)
    work_experience: Mapped[str | None] = mapped_column(String(20), nullable=True, sort_order=9)
    research_experience: Mapped[str | None] = mapped_column(String(20), nullable=True, sort_order=10)
    publication: Mapped[str | None] = mapped_column(String(20), nullable=True, sort_order=11)
    recommendation_letter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=12)
    motivation_letter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=13)
    cv_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=14)
    passport_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=15)

    # Relationship
    scholarship: Mapped["Scholarship"] = relationship(
        back_populates="requirement",
    )

    def __repr__(self) -> str:
        return f"<ScholarshipRequirement {self.requirement_id}>"
