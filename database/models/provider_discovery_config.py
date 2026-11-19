"""Provider Discovery Configuration model.

Stores per-country configuration for provider discovery, making the system
configurable via database rather than code changes.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.country import Country


class ProviderDiscoveryConfig(Base, TimestampMixin):
    """Configuration for provider discovery per country.

    Defines:
    - Discovery surfaces (where to look for providers)
    - Allowed TLD patterns (official domain patterns)
    - Keyword filters (what terms suggest scholarship activity)
    - Verification thresholds
    """

    __tablename__ = "provider_discovery_config"

    config_id: Mapped[uuid.UUID] = mapped_column(
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
        comment="URL to crawl for discovering providers"
    )
    discovery_strategy: Mapped[str] = mapped_column(
        String(50), nullable=False, default="link_discovery", sort_order=3,
        comment="Strategy: link_discovery, sitemap_discovery, structured_directory"
    )
    allowed_tlds: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, sort_order=4,
        comment="List of allowed TLD patterns: ['.go.jp', '.ac.jp']"
    )
    keyword_filters: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, sort_order=5,
        comment="Keywords to filter discovered URLs: ['scholarship', 'grant']"
    )
    exclude_patterns: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, sort_order=6,
        comment="URL patterns to exclude: ['/news/', '/events/']"
    )
    auto_verify_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, sort_order=7,
        comment="Whether to auto-verify candidates without human review"
    )
    confidence_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.8, sort_order=8,
        comment="Minimum confidence for auto-verification (0.0-1.0)"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, sort_order=9,
        comment="Discovery priority (1-5, lower is higher priority)"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, sort_order=10,
        comment="Whether this discovery config is active and should be processed"
    )
    organization_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="University", sort_order=11,
        comment=(
            "Type of organization this config discovers: "
            "University, Government, Foundation, Research, Agency, Other"
        )
    )
    max_urls_per_source: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, sort_order=12,
        comment="Maximum URLs to process per source during discovery"
    )
    custom_settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, sort_order=13,
        comment="Strategy-specific settings"
    )

    # Relationships
    country: Mapped["Country"] = relationship(
        back_populates="provider_discovery_configs",
    )

    def __repr__(self) -> str:
        return f"<ProviderDiscoveryConfig {self.country_id} -> {self.discovery_surface_url}>"
