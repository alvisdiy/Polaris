"""Provider Discovery Attempt model for tracking discovery operations.

Every attempt to discover a provider from a discovery surface is recorded
for observability, debugging, and audit purposes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.country import Country
    from database.models.provider import Provider


class ProviderDiscoveryAttempt(Base, TimestampMixin):
    """Record of a single provider discovery attempt.

    Tracks:
    - Where the candidate was found (discovery surface)
    - What was found (candidate URL)
    - Verification checks performed
    - Outcome (created, duplicate, rejected, error)
    """

    __tablename__ = "provider_discovery_attempt"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0
    )
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=1,
    )
    discovery_surface_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, sort_order=2,
        comment="The page that was crawled for discovery"
    )
    discovered_url: Mapped[str] = mapped_column(
        String(2048), nullable=False, sort_order=3,
        comment="The candidate provider URL found"
    )
    discovery_method: Mapped[str] = mapped_column(
        String(50), nullable=False, sort_order=4,
        comment="Strategy used: link_discovery, sitemap_discovery, etc."
    )
    domain_pattern_matched: Mapped[str | None] = mapped_column(
        String(100), nullable=True, sort_order=5,
        comment="The TLD pattern that matched (e.g., .go.jp)"
    )
    keywords_matched: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, sort_order=6,
        comment="Keywords that triggered the match"
    )
    http_status: Mapped[int | None] = mapped_column(
        Integer, nullable=True, sort_order=7,
        comment="HTTP status code when fetching discovered_url"
    )
    verification_checks: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, sort_order=8,
        comment="Results of each verification check"
    )
    outcome: Mapped[str] = mapped_column(
        String(20), nullable=False, sort_order=9,
        comment="Result: created, duplicate, rejected, error"
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider.provider_id", ondelete="SET NULL"),
        nullable=True,
        sort_order=10,
        comment="FK to Provider if one was created"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, sort_order=11
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, sort_order=12
    )

    # Relationships
    country: Mapped["Country"] = relationship(
        back_populates="provider_discovery_attempts",
    )
    provider: Mapped["Provider | None"] = relationship(
        back_populates="discovery_attempts",
    )

    def __repr__(self) -> str:
        return f"<ProviderDiscoveryAttempt {self.discovered_url} -> {self.outcome}>"
