import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

class SourceRegistry(Base, TimestampMixin):
    __tablename__ = "source_registry"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0
    )
    source_name: Mapped[str] = mapped_column(
        String(255), nullable=False, sort_order=1
    )
    country_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="RESTRICT"),
        nullable=True,
        sort_order=2,
    )
    provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider.provider_id", ondelete="RESTRICT"),
        nullable=True,
        sort_order=3,
    )
    official_url: Mapped[str] = mapped_column(
        String(2048), unique=True, nullable=False, sort_order=4
    )
    crawl_entry_url: Mapped[str] = mapped_column(
        String(2048), unique=True, nullable=False, sort_order=5
    )
    crawl_method: Mapped[str] = mapped_column(
        String(50), nullable=False, sort_order=6
    )
    connector_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, sort_order=7
    )
    crawl_frequency: Mapped[str] = mapped_column(
        String(50), nullable=False, sort_order=8
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, sort_order=9
    )
    language: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, sort_order=10
    )
    timezone: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, sort_order=11
    )
    robots_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, sort_order=12
    )
    requires_login: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, sort_order=13
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="Active", sort_order=14
    )
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=15
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=16
    )

    # Relationships
    country: Mapped[Optional["Country"]] = relationship(
        "Country",
        back_populates="source_registries",
        foreign_keys=[country_id]
    )
    provider: Mapped[Optional["Provider"]] = relationship(
        "Provider",
        back_populates="source_registries",
        foreign_keys=[provider_id]
    )
    raw_documents: Mapped[list["RawDocument"]] = relationship(
        "RawDocument",
        back_populates="source",
    )
    scholarships: Mapped[list["Scholarship"]] = relationship(
        "Scholarship",
        back_populates="source",
    )

    def __repr__(self) -> str:
        return f"<SourceRegistry {self.source_name} ({self.status})>"
