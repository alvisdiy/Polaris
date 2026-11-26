from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.country import Country
    from database.models.provider import Provider
    from database.models.scholarship_benefit import ScholarshipBenefit
    from database.models.scholarship_candidate_revision import ScholarshipCandidateRevision
    from database.models.scholarship_degree_level import ScholarshipDegreeLevel
    from database.models.scholarship_requirement import ScholarshipRequirement
    from database.models.scholarship_review_action import ScholarshipReviewAction
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

    # --- M9 review / curation state ---
    # extraction_status remains THE publication boundary (approved only is
    # visible to API + matching). The columns below describe *why* a record
    # is where it is, and carry the reviewer's verdict; they never gate
    # visibility on their own.
    extraction_confidence: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, sort_order=15,
        comment="Extractor confidence 0.0-1.0. Routing only; never a publication decision.",
    )
    quality_report: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, sort_order=16,
        comment="Publication-gate result: per-field KNOWN/UNKNOWN/NOT_APPLICABLE/MISSING/CONFLICTING",
    )
    conflicts: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True, sort_order=17,
        comment="Unresolved cross-source disagreements: [{field, values:[{source_url, value}]}]",
    )
    field_provenance: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, sort_order=18,
        comment="Per-field origin: {field: {source_url, raw_document_id, extracted_at, confidence}}",
    )
    provenance_origin: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, sort_order=19,
        comment="How this record entered the KB: exploration | seed_script | connector | manual",
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=20,
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, sort_order=21,
    )
    review_notes: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, sort_order=22,
        comment="Latest reviewer rationale. Full history lives in scholarship_review_action.",
    )

    # --- Funding amount, as stated (semantics A, 2026-11-26) ---
    # The amount is the figure the official page states, in the currency
    # and for the period the page states. No FX conversion and no period
    # conversion: both would publish a number the source never gave.
    # NULL amount means the source stated no cash figure. A tuition waiver
    # therefore keeps amount NULL (never 0, which would read as worthless);
    # the waiver itself is carried by funding_type.
    funding_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True, sort_order=23,
        comment="Cash figure exactly as stated by the source; NULL when unstated",
    )
    funding_currency: Mapped[Optional[str]] = mapped_column(
        String(3), nullable=True, sort_order=24,
        comment="ISO 4217 code as stated (EUR, USD); NULL when unstated; never converted",
    )
    funding_period: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, sort_order=25,
        comment="Period the stated amount belongs to: total | per_year | per_month | per_semester | one_off",
    )
    funding_duration_months: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, sort_order=26,
        comment="Funding duration in months, only when the source states a duration",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, sort_order=27,
        comment="Excerpt from the official page itself; never written by a model or a person at Polaris",
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
    degree_levels: Mapped[list["ScholarshipDegreeLevel"]] = relationship(
        "ScholarshipDegreeLevel",
        back_populates="scholarship",
        cascade="all, delete-orphan",
        order_by="ScholarshipDegreeLevel.degree",
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
    review_actions: Mapped[list["ScholarshipReviewAction"]] = relationship(
        "ScholarshipReviewAction",
        back_populates="scholarship",
        cascade="all, delete-orphan",
    )
    # Proposed-but-unpublished revisions (M9.1). Separate from `versions`
    # because their existence means a value has NOT been published.
    candidate_revisions: Mapped[list["ScholarshipCandidateRevision"]] = relationship(
        "ScholarshipCandidateRevision",
        back_populates="scholarship",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_scholarship_identity",
            "identity_key",
            unique=True,
            postgresql_where=sa.text("identity_key IS NOT NULL"),
        ),
        Index("ix_scholarship_name", "scholarship_name"),
        Index("ix_scholarship_provider_id", "provider_id"),
        Index("ix_scholarship_country_id", "country_id"),
        Index("ix_scholarship_degree", "degree"),
        Index("ix_scholarship_funding_type", "funding_type"),
        Index("ix_scholarship_extraction_status", "extraction_status"),
        Index("ix_scholarship_deadline_state", "deadline_state"),
        Index("ix_scholarship_provenance_origin", "provenance_origin"),
        Index("ix_scholarship_reviewed_at", "reviewed_at"),
    )

    def __repr__(self) -> str:
        return f"<Scholarship {self.scholarship_name} ({self.extraction_status})>"
