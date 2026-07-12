from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.provider import Provider
    from database.models.scholarship import Scholarship
    from database.models.source_registry import SourceRegistry
    from database.models.university import University


class Country(Base, TimestampMixin):
    __tablename__ = "country"

    country_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0)
    iso2: Mapped[str] = mapped_column(String(2), unique=True, nullable=False, sort_order=1)
    iso3: Mapped[str] = mapped_column(String(3), unique=True, nullable=False, sort_order=2)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, sort_order=3)

    # Relationships within this milestone
    providers: Mapped[list["Provider"]] = relationship(
        back_populates="country",
    )
    universities: Mapped[list["University"]] = relationship(
        back_populates="country",
    )
    source_registries: Mapped[list["SourceRegistry"]] = relationship(
        back_populates="country",
    )
    scholarships: Mapped[list["Scholarship"]] = relationship(
        back_populates="country",
    )

    def __repr__(self) -> str:
        return f"<Country {self.iso3}: {self.name}>"
