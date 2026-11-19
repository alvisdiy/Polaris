from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.models.base import Base, TimestampMixin
from database.utils import new_uuid


class SourceVerificationState:
    """Explicit verification lifecycle.

    Documented in `country-exploration-specification.md` §14 and mirrored by
    `services/exploration/verification_engine.py`. Declared here so persistence
    and the verifier cannot drift apart, and so review tooling can validate a
    transition without importing the engine.
    """

    DISCOVERED = "DISCOVERED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


class SourcePageType:
    """What a verified source entry URL actually is.

    Phase 1 of M9: a source's landing page is not assumed to be a
    scholarship. This drives acquisition behaviour — only
    ``SCHOLARSHIP_PAGE`` is extracted directly; the rest must first be
    mined for scholarship-bearing URLs.
    """

    SCHOLARSHIP_PAGE = "scholarship_page"
    SCHOLARSHIP_INDEX = "scholarship_index"
    PROVIDER_PAGE = "provider_page"
    SOURCE_PAGE = "source_page"
    UNKNOWN = "unknown"


class SourceAcquisitionState:
    """Whether acquisition has been attempted for this source, and how it went.

    Kept separate from verification: a source can be VERIFIED and still have
    an acquisition that failed (JS-gated portal, 403 on the detail path).
    Collapsing the two would hide real operational failures.

    These are the values the acquisition layer actually writes
    (`services/exploration/acquisition_policy.py` re-exports this class rather
    than declaring a second vocabulary). An earlier version of this class
    listed NOT_ATTEMPTED / IN_PROGRESS / COMPLETED, which nothing has ever
    written: two vocabularies for one column means one of them is always
    wrong, and reading it as a query filter is how that becomes a bug.
    """

    PENDING = "pending"
    ACQUIRED = "acquired"
    NO_SCHOLARSHIP_PAGES = "no_scholarship_pages"
    FAILED = "failed"
    SKIPPED = "skipped"


if TYPE_CHECKING:
    from database.models.country import Country
    from database.models.provider import Provider
    from database.models.raw_document import RawDocument
    from database.models.scholarship import Scholarship


class SourceRegistry(Base, TimestampMixin):
    __tablename__ = "source_registry"

    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid, sort_order=0)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, sort_order=1)
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
    official_url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, sort_order=4)
    crawl_entry_url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, sort_order=5)
    crawl_method: Mapped[str] = mapped_column(String(50), nullable=False, sort_order=6)
    connector_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, sort_order=7)
    crawl_frequency: Mapped[str] = mapped_column(String(50), nullable=False, sort_order=8)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, sort_order=9)
    language: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, sort_order=10)
    timezone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, sort_order=11)
    robots_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, sort_order=12)
    requires_login: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, sort_order=13)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="Active", sort_order=14)
    last_crawled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, sort_order=15)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, sort_order=16)
    verification_state: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, sort_order=17,
        comment="Explicit verification lifecycle: DISCOVERED, NEEDS_REVIEW, VERIFIED, REJECTED, DEPRECATED",
    )
    confidence: Mapped[Optional[float]] = mapped_column(
        sa.Float(), nullable=True, sort_order=18,
        comment="Verification confidence 0.0-1.0 (routing only, not final state)",
    )
    discovered_via: Mapped[Optional[dict]] = mapped_column(
        sa.JSON(), nullable=True, sort_order=19,
        comment="Provenance: frontier chain that produced this source",
    )

    # --- M9: acquisition policy + observability ---
    page_type: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, sort_order=20,
        comment="What the entry URL is: scholarship_page | scholarship_index | provider_page | source_page | unknown",
    )
    canonical_url: Mapped[Optional[str]] = mapped_column(
        String(2048), nullable=True, sort_order=21,
        comment=(
            "normalize_url(official_url). One logical URL -> one source identity "
            "despite redirects/tracking params."
        ),
    )
    url_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, sort_order=22,
        comment="sha256 of canonical_url. Indexed, so acquisition never depends on a raw string match.",
    )
    acquisition_state: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, sort_order=23,
        comment="not_attempted | in_progress | completed | no_scholarship_pages | failed",
    )
    acquisition_error: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, sort_order=24,
        comment="Last acquisition failure. Acquisition failures are never swallowed silently.",
    )
    acquisition_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, sort_order=25,
    )
    last_acquisition_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, sort_order=26,
    )
    scholarship_page_urls: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True, sort_order=27,
        comment="Scholarship-bearing URLs discovered on this source, with their page classification.",
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, sort_order=28,
    )

    # Relationships
    country: Mapped[Optional["Country"]] = relationship(
        "Country", back_populates="source_registries", foreign_keys=[country_id]
    )
    provider: Mapped[Optional["Provider"]] = relationship(
        "Provider", back_populates="source_registries", foreign_keys=[provider_id]
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
        return (
            f"<SourceRegistry {self.source_name} "
            f"(status={self.status}, verification={self.verification_state})>"
        )

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    def is_verified(self) -> bool:
        """True when this source is trusted enough to feed acquisition."""
        return self.verification_state == SourceVerificationState.VERIFIED

    def needs_review(self) -> bool:
        return self.verification_state == SourceVerificationState.NEEDS_REVIEW

    def can_transition_to(self, new_state: str) -> bool:
        """Whether a verification_state transition is legal.

        Terminal states do not resurrect silently. DEPRECATED and REJECTED are
        only reachable from a reviewed state, never straight out of a fresh
        DISCOVERED row, so a bad URL cannot be condemned by one bad fetch.
        """
        allowed = {
            SourceVerificationState.DISCOVERED: {
                SourceVerificationState.NEEDS_REVIEW,
                SourceVerificationState.VERIFIED,
                SourceVerificationState.REJECTED,
            },
            SourceVerificationState.NEEDS_REVIEW: {
                SourceVerificationState.VERIFIED,
                SourceVerificationState.REJECTED,
                SourceVerificationState.DISCOVERED,
            },
            SourceVerificationState.VERIFIED: {
                SourceVerificationState.NEEDS_REVIEW,
                SourceVerificationState.DEPRECATED,
                SourceVerificationState.REJECTED,
            },
            SourceVerificationState.REJECTED: {
                SourceVerificationState.NEEDS_REVIEW,
            },
            SourceVerificationState.DEPRECATED: {
                SourceVerificationState.NEEDS_REVIEW,
            },
        }
        return new_state in allowed.get(self.verification_state or "", set())
