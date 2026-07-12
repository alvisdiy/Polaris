"""Scholarship benefits — child of Scholarship (1:1)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.scholarship import Scholarship


class ScholarshipBenefit(Base, TimestampMixin):
    __tablename__ = "scholarship_benefit"

    benefit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0)
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        sort_order=1,
    )
    tuition_fee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=2)
    monthly_allowance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=3)
    accommodation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=4)
    health_insurance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=5)
    travel_ticket: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=6)
    research_grant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=7)

    # Relationship
    scholarship: Mapped["Scholarship"] = relationship(
        back_populates="benefit",
    )

    def __repr__(self) -> str:
        return f"<ScholarshipBenefit {self.benefit_id}>"
