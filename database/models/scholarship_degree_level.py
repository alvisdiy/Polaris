"""Scholarship degree levels — the award's levels when a page states several.

``scholarship.degree`` holds one level. Many national databases state a set
instead ("Academic level: Doctoral degree program / Master's degree program"),
and a single column could only record that as NULL — which dropped the record
out of every degree filter and out of matching. These rows carry the set.

The single column is kept: it is what most records have, and it is what the
matching engine's primary filter reads. A row here is not a replacement for it,
it is the multi-valued case the column cannot express.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.scholarship import Scholarship


class ScholarshipDegreeLevel(Base, TimestampMixin):
    __tablename__ = "scholarship_degree_level"
    __table_args__ = (
        UniqueConstraint(
            "scholarship_id", "degree", name="uq_scholarship_degree_level"
        ),
    )

    degree_level_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0
    )
    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        sort_order=1,
    )
    # Canonical value from services.domain.vocabulary.DEGREE. Enforced by the
    # mapper and the review service, the same way scholarship.degree is.
    degree: Mapped[str] = mapped_column(String(32), nullable=False, sort_order=2)

    scholarship: Mapped["Scholarship"] = relationship(back_populates="degree_levels")

    def __repr__(self) -> str:
        return f"<ScholarshipDegreeLevel {self.degree}>"
