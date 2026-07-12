from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.models.enums import ProviderType
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.country import Country
    from database.models.scholarship import Scholarship
    from database.models.source_registry import SourceRegistry


class Provider(Base, TimestampMixin):
    __tablename__ = "provider"

    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0)
    provider_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, sort_order=1)
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False, sort_order=2)
    provider_type: Mapped[ProviderType] = mapped_column(String(20), nullable=False, sort_order=3)
    country_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="RESTRICT"),
        nullable=True,
        sort_order=4,
    )
    official_url: Mapped[str | None] = mapped_column(String(2048), nullable=True, sort_order=5)

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

    def __repr__(self) -> str:
        return f"<Provider {self.provider_code}: {self.provider_name}>"
