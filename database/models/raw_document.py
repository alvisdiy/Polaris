from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.source_registry import SourceRegistry


class RawDocument(Base, TimestampMixin):
    """Stores raw downloaded source documents for the pipeline."""

    __tablename__ = "raw_document"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_registry.source_id", ondelete="RESTRICT"),
        nullable=False,
        sort_order=1,
    )
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, sort_order=2)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False, sort_order=3)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False, sort_order=4)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, sort_order=5)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, sort_order=6)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, sort_order=7)
    etag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, sort_order=8)
    last_modified: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, sort_order=9)
    crawl_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, sort_order=10)
    processing_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", sort_order=11)

    # Relationships
    source: Mapped["SourceRegistry"] = relationship(
        "SourceRegistry",
        back_populates="raw_documents",
        foreign_keys=[source_id],
    )

    __table_args__ = (UniqueConstraint("source_id", "checksum", name="uq_raw_document_source_checksum"),)

    def __repr__(self) -> str:
        return f"<RawDocument {self.document_id} ({self.processing_status})>"
