from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, TEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.country import Country
    from database.models.provider import Provider
    from database.models.scholarship_benefit import ScholarshipBenefit
    from database.models.scholarship_requirement import ScholarshipRequirement
    from database.models.scholarship_timeline import ScholarshipTimeline
    from database.models.scholarship_version import ScholarshipVersion
    from database.models.source_registry import SourceRegistry
    from database.models.university import University


class Scholarship(Base, TimestampMixin):
    __tablename__ = "scholarship"

    scholarship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0
    )
    scholarship_name: Mapped[str] = mapped_column(String(512), nullable=False, sort_order=1)
    degree: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, sort_order=2)
    funding_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, sort_order=3)
    field_of_study: Mapped[list[str]] = mapped_column(ARRAY(TEXT), nullable=False, server_default="{}", sort_order=4)
    application_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, sort_order=5)
    official_page_url: Mapped[str] = mapped_column(String(2048), nullable=False, sort_order=6)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider.provider_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=7,
    )
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=8,
    )
    university_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("university.university_id", ondelete="RESTRICT"),
        nullable=True,
        sort_order=9,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_registry.source_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=10,
    )
    extraction_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending_review", sort_order=11)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, sort_order=12)
    deadline_state: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, sort_order=13,
        comment="Deadline freshness: active | expired | unknown | rolling (NULL = not yet classified)",
    )
    identity_key: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, sort_order=14,
        comment="Canonical dedup hash: provider + normalized name + country (same opportunity across sites = 1 row)",
    )

    # Relationships — reference entities
    provider: Mapped["Provider"] = relationship(
        "Provider",
        back_populates="scholarships",
        foreign_keys=[provider_id],
    )
    country: Mapped["Country"] = relationship(
        "Country",
        back_populates="scholarships",
        foreign_keys=[country_id],
    )
    university: Mapped[Optional["University"]] = relationship(
        "University",
        back_populates="scholarships",
        foreign_keys=[university_id],
    )
    source: Mapped["SourceRegistry"] = relationship(
        "SourceRegistry",
        back_populates="scholarships",
        foreign_keys=[source_id],
    )

    # Relationships — child entities (cascade delete)
    requirement: Mapped[Optional["ScholarshipRequirement"]] = relationship(
        "ScholarshipRequirement",
        back_populates="scholarship",
        cascade="all, delete-orphan",
        uselist=False,
    )
    benefit: Mapped[Optional["ScholarshipBenefit"]] = relationship(
        "ScholarshipBenefit",
        back_populates="scholarship",
        cascade="all, delete-orphan",
        uselist=False,
    )
    timeline: Mapped[Optional["ScholarshipTimeline"]] = relationship(
        "ScholarshipTimeline",
        back_populates="scholarship",
        cascade="all, delete-orphan",
        uselist=False,
    )
    versions: Mapped[list["ScholarshipVersion"]] = relationship(
        "ScholarshipVersion",
        back_populates="scholarship",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("uq_scholarship_identity", "identity_key", unique=True, postgresql_where=sa.text("identity_key IS NOT NULL")),
        Index("ix_scholarship_name", "scholarship_name"),
        Index("ix_scholarship_provider_id", "provider_id"),
        Index("ix_scholarship_country_id", "country_id"),
        Index("ix_scholarship_degree", "degree"),
        Index("ix_scholarship_funding_type", "funding_type"),
        Index("ix_scholarship_extraction_status", "extraction_status"),
        Index("ix_scholarship_deadline_state", "deadline_state"),
    )

    def __repr__(self) -> str:
        return f"<Scholarship {self.scholarship_name} ({self.extraction_status})>"
