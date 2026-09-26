from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid

if TYPE_CHECKING:
    from database.models.country import Country
    from database.models.source_registry import SourceRegistry


class FrontierState:
    """Candidate processing states (explicit lifecycle, auditable)."""

    PENDING = "pending"          # discovered, not yet claimed
    IN_PROGRESS = "in_progress"  # claimed under lease, being processed
    DONE = "done"                # processed to a terminal outcome
    FAILED = "failed"            # retries exhausted
    REJECTED = "rejected"        # clearly irrelevant (evidence-backed)
    DEFERRED = "deferred"        # retained at low priority, not discarded


class CandidateType:
    OPPORTUNITY = "opportunity"
    PROVIDER = "provider"
    SOURCE = "source"
    UNKNOWN = "unknown"


class CandidateOrigin:
    WEB_SEARCH = "web_search"
    SEED = "seed"
    KNOWN_SOURCE = "known_source"
    LINK_EXPANSION = "link_expansion"
    BATCH_IMPORT = "batch_import"


class DiscoveryFrontier(Base, TimestampMixin):
    """Persistent discovery state for one candidate URL.

    Not merely a URL queue: each row carries the discovery provenance
    (origin, query, evidence observations) needed to answer what was
    discovered, where, why, and what happened when it was processed.

    Deduplication: UNIQUE (country_id, url_hash). Re-discovery merges
    evidence observations instead of creating duplicate rows.
    """

    __tablename__ = "discovery_frontier"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid
    )
    country_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("country.country_id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False, comment="Normalized candidate URL")
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="sha256 of normalized URL")

    candidate_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CandidateType.UNKNOWN,
        comment="opportunity | provider | source | unknown (advisory hint, refined by classifier)",
    )
    origin: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="web_search | seed | known_source | link_expansion | batch_import",
    )
    origin_query: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, comment="Search query that produced this candidate"
    )
    origin_url: Mapped[str | None] = mapped_column(
        String(2048), nullable=True, comment="Page/URL where this candidate was found"
    )
    origin_url_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Hash of origin_url (indexed discovery-chain lookup)"
    )
    origin_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_registry.source_id", ondelete="SET NULL"),
        nullable=True,
    )

    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5, comment="Lower = processed first")

    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FrontierState.PENDING,
        comment="pending | in_progress | done | failed | rejected | deferred",
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="{observations: [...], page_signals: {...}} — appended on every rediscovery",
    )
    outcome: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Classifier label/routing, resolution result, verify state, history",
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exploration_run.run_id", ondelete="SET NULL"),
        nullable=True,
    )

    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    country: Mapped["Country"] = relationship("Country", foreign_keys=[country_id], lazy="raise")
    origin_source: Mapped["SourceRegistry | None"] = relationship(
        "SourceRegistry", foreign_keys=[origin_source_id], lazy="raise"
    )

    __table_args__ = (
        Index("uq_frontier_country_urlhash", "country_id", "url_hash", unique=True),
        Index("ix_frontier_claim", "country_id", "state", "priority"),
        Index("ix_frontier_lease", "state", "lease_expires_at"),
        Index("ix_frontier_origin_url_hash", "origin_url_hash"),
    )

    def __repr__(self) -> str:
        return f"<DiscoveryFrontier {self.state} d{self.depth} {self.url[:60]}>"
