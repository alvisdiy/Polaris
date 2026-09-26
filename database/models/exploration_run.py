from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid


class ExplorationRunStatus:
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExplorationRun(Base, TimestampMixin):
    """One bounded execution of the Country Exploration Engine.

    Snapshots the country configuration and accumulates run metrics so every
    discovered artifact can be traced back to the run that produced it.
    """

    __tablename__ = "exploration_run"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExplorationRunStatus.RUNNING,
        comment="running | completed | failed",
    )
    config_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, comment="Country config used for this run"
    )
    bounds_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, comment="Effective exploration bounds"
    )
    metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, comment="Accumulated run counters"
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ExplorationRun {self.run_id} {self.status}>"
