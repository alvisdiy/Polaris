import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import ARRAY, TEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid


class Scholarship(Base, TimestampMixin):
    __tablename__ = "scholarship"

    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0
    )
    scholarship_name: Mapped[str] = mapped_column(
        String(512), nullable=False, sort_order=1
    )
    degree: Mapped[str] = mapped_column(
        String(50), nullable=False, sort_order=2
    )
    funding_type: Mapped[str] = mapped_column(
        String(50), nullable=False, sort_order=3
    )
    field_of_study: Mapped[list[str]] = mapped_column(
        ARRAY(TEXT), nullable=False, server_default="{}", sort_order=4
    )
    application_url: Mapped[Optional[str]] = mapped_column(
        String(2048), nullable=True, sort_order=5
    )
    official_page_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, sort_order=6
    )
    application_open: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, sort_order=7
    )
    application_deadline: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, sort_order=8
    )
    application_cycle: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, sort_order=9
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider.provider_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=10,
    )
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=11,
    )
    university_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("university.university_id", ondelete="RESTRICT"),
        nullable=True,
        sort_order=12,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_registry.source_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=13,
    )
    extraction_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending_review", sort_order=14
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=15
    )

    # Relationships
    provider: Mapped["Provider"] = relationship(
        "Provider",
        back_populates="scholarships",
        foreign_keys=[provider_id]
    )
    country: Mapped["Country"] = relationship(
        "Country",
        back_populates="scholarships",
        foreign_keys=[country_id]
    )
    university: Mapped[Optional["University"]] = relationship(
        "University",
        back_populates="scholarships",
        foreign_keys=[university_id]
    )
    source: Mapped["SourceRegistry"] = relationship(
        "SourceRegistry",
        back_populates="scholarships",
        foreign_keys=[source_id]
    )

    __table_args__ = (
        Index("ix_scholarship_name", "scholarship_name"),
        Index("ix_scholarship_provider_id", "provider_id"),
        Index("ix_scholarship_country_id", "country_id"),
        Index("ix_scholarship_degree", "degree"),
        Index("ix_scholarship_funding_type", "funding_type"),
        Index("ix_scholarship_deadline", "application_deadline"),
        Index("ix_scholarship_cycle", "application_cycle"),
        Index("ix_scholarship_extraction_status", "extraction_status"),
        Index("ix_scholarship_provider_cycle", "provider_id", "application_cycle"),
    )

    def __repr__(self) -> str:
        return f"<Scholarship {self.scholarship_name} ({self.extraction_status})>"
