"""Provider model with verification lifecycle for discovered scholarship providers.

The Provider entity represents organizations that offer scholarships:
- Government agencies (Ministries of Education, etc.)
- Universities
- Foundations
- NGOs
- Companies

Providers are discovered through the Provider Discovery pipeline and undergo
a verification lifecycle before becoming active sources for scholarship acquisition.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.models.enums import ProviderType
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.country import Country
    from database.models.provider_discovery_attempt import ProviderDiscoveryAttempt
    from database.models.scholarship import Scholarship
    from database.models.source_registry import SourceRegistry


class Provider(Base, TimestampMixin):
    """Scholarship provider organization with verification lifecycle.

    Verification Lifecycle:
    - discovered: Found via automated discovery
    - candidate: Passed initial heuristic checks
    - verified: Deterministic verification passed
    - registered: Active in SourceRegistry
    - rejected: Failed verification or human review
    - deprecated: Previously active, now inactive
    """

    __tablename__ = "provider"

    # Core identity
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0
    )
    provider_code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, sort_order=1,
        comment="Unique identifier derived from normalized domain (e.g., JASSO_GO_JP)"
    )
    provider_name: Mapped[str] = mapped_column(
        String(255), nullable=False, sort_order=2
    )
    provider_type: Mapped[ProviderType] = mapped_column(
        String(20), nullable=False, sort_order=3
    )
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="RESTRICT"),
        nullable=True,
        sort_order=4,
    )
    official_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, sort_order=5
    )

    # Verification lifecycle fields
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="discovered", sort_order=6,
        comment="Lifecycle state: discovered, needs_review, candidate, verified, registered, rejected, deprecated"
    )
    identity_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, sort_order=14,
        comment="Resolved identity hash (registered domain + normalized name + country)"
    )
    merged_into_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, sort_order=15,
        comment="Set when this duplicate provider row was merged into another"
    )
    identity_confidence: Mapped[float | None] = mapped_column(
        sa.Float(), nullable=True, sort_order=16,
        comment="Confidence of the identity resolution (0.0-1.0)"
    )
    discovery_source: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, sort_order=7,
        comment="URL where this provider was discovered"
    )
    discovery_method: Mapped[str | None] = mapped_column(
        String(50), nullable=True, sort_order=8,
        comment="Discovery strategy used: government_portal, education_directory, etc."
    )
    discovery_evidence: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, sort_order=9,
        comment="Structured evidence: anchor_text, keywords_matched, tld_matched, etc."
    )
    discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=10
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=11
    )
    verified_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True, sort_order=12,
        comment="'auto' for automated verification, or user identifier for human review"
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, sort_order=13
    )

    # Relationships
    country: Mapped["Country | None"] = relationship(
        back_populates="providers",
        foreign_keys=[country_id],
    )
    source_registries: Mapped[list["SourceRegistry"]] = relationship(
        back_populates="provider",
    )
    scholarships: Mapped[list["Scholarship"]] = relationship(
        back_populates="provider",
    )
    discovery_attempts: Mapped[list["ProviderDiscoveryAttempt"]] = relationship(
        back_populates="provider",
    )

    def __repr__(self) -> str:
        return f"<Provider {self.provider_code}: {self.provider_name} ({self.verification_status})>"

    def is_verified(self) -> bool:
        """Check if provider has passed verification."""
        return self.verification_status in ("verified", "registered")

    def is_active(self) -> bool:
        """Check if provider is active in acquisition pipeline."""
        return self.verification_status == "registered"
