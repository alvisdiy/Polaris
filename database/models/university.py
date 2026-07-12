import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid


class University(Base, TimestampMixin):
    __tablename__ = "university"

    university_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0
    )
    university_code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, sort_order=1
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False, sort_order=2
    )
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=3,
    )
    official_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, sort_order=4
    )

    # Relationships
    country: Mapped["Country"] = relationship(
        back_populates="universities",
        foreign_keys=[country_id],
    )
    scholarships: Mapped[list["Scholarship"]] = relationship(
        back_populates="university",
    )

    def __repr__(self) -> str:
        return f"<University {self.university_id}: {self.name}>"
