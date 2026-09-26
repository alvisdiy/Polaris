"""Repository primitives for the DiscoveryFrontier.

Implements the operational semantics the exploration engine depends on:
- evidence-merging upsert (provenance survives deduplication)
- lease-based claiming (FOR UPDATE SKIP LOCKED, stale recovery)
- bounded admission (per-country candidate cap, per-domain page cap, max depth)
- retry backoff and terminal states
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from database.models.discovery_frontier import (
    CandidateType,
    DiscoveryFrontier,
    FrontierState,
)
from services.exploration.url_utils import domain_of, url_hash


@dataclass
class FrontierObservation:
    """One provenance observation attached to a candidate."""

    origin: str
    source_url: str | None = None
    origin_query: str | None = None
    search_provider: str | None = None
    rank: int | None = None
    snippet: str | None = None
    anchor_text: str | None = None
    title: str | None = None
    run_id: str | None = None
    at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"origin": self.origin, "at": self.at}
        for key in (
            "source_url", "origin_query", "search_provider", "rank",
            "snippet", "anchor_text", "title", "run_id",
        ):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data


@dataclass
class FrontierBounds:
    """Runtime admission bounds for one run."""

    max_candidates: int = 2000
    max_pages_per_domain: int = 15
    max_depth: int = 3
    processed_domains: dict[str, int] = field(default_factory=dict)

    def domain_budget_left(self, domain: str) -> int:
        return max(0, self.max_pages_per_domain - self.processed_domains.get(domain, 0))


class FrontierRepository:
    """Persistence layer for DiscoveryFrontier with merge/claim semantics."""

    def __init__(self, session: Session, bounds: FrontierBounds | None = None) -> None:
        self.session = session
        self.bounds = bounds or FrontierBounds()
        self.dedup_merges = 0
        self.admitted = 0
        self.rejected_by_bounds = 0

    # ------------------------------------------------------------------
    # Upsert with evidence merge
    # ------------------------------------------------------------------

    def upsert_candidate(
        self,
        country_id,
        url: str,
        *,
        origin: str,
        candidate_type: str = CandidateType.UNKNOWN,
        origin_query: str | None = None,
        origin_url: str | None = None,
        origin_source_id=None,
        depth: int = 0,
        priority: int = 5,
        observation: FrontierObservation | None = None,
        run_id=None,
    ) -> tuple[DiscoveryFrontier, bool]:
        """Insert a candidate or merge evidence into an existing row.

        Returns (candidate, created). Merging appends the observation to
        evidence.observations and keeps the best (lowest) priority —
        provenance survives deduplication.
        """
        normalized = url_hash(url)
        domain = domain_of(url)

        # Admission bounds
        if depth > self.bounds.max_depth:
            self.rejected_by_bounds += 1
            return self._existing_or_none(country_id, normalized), False
        if self.bounds.domain_budget_left(domain) <= 0:
            self.rejected_by_bounds += 1
            return self._existing_or_none(country_id, normalized), False

        existing = (
            self.session.query(DiscoveryFrontier)
            .filter(
                DiscoveryFrontier.country_id == country_id,
                DiscoveryFrontier.url_hash == normalized,
            )
            .first()
        )

        if existing:
            self._merge_observation(existing, observation)
            previous_priority = existing.priority
            existing.priority = min(previous_priority, priority)
            # Refine advisory type: known > unknown
            if existing.candidate_type == CandidateType.UNKNOWN and candidate_type != CandidateType.UNKNOWN:
                existing.candidate_type = candidate_type
            # Re-queue candidates that were consumed but not condemned, so
            # strictly better evidence gets re-analyzed. REJECTED is an
            # evidence-backed verdict and stays terminal: resurrecting it
            # would spend page budget on pages already judged irrelevant.
            # `previous_priority` is read before the merge, otherwise the
            # comparison below is always false.
            if (
                existing.state in (FrontierState.DONE, FrontierState.DEFERRED)
                and priority < previous_priority
            ):
                existing.state = FrontierState.PENDING
            self.dedup_merges += 1
            return existing, False

        candidate = DiscoveryFrontier(
            country_id=country_id,
            url=url[:2048],
            url_hash=normalized,
            candidate_type=candidate_type,
            origin=origin,
            origin_query=(origin_query or "")[:2048] or None,
            origin_url=(origin_url or "")[:2048] or None,
            origin_url_hash=url_hash(origin_url) if origin_url else None,
            origin_source_id=origin_source_id,
            depth=depth,
            priority=priority,
            state=FrontierState.PENDING,
            evidence={"observations": [], "page_signals": {}},
            run_id=run_id,
        )
        self._merge_observation(candidate, observation)
        self.session.add(candidate)
        self.session.flush()
        self.admitted += 1
        if domain:
            self.bounds.processed_domains[domain] = self.bounds.processed_domains.get(domain, 0) + 1
        return candidate, True

    def _existing_or_none(self, country_id, url_hash_value) -> DiscoveryFrontier | None:
        return (
            self.session.query(DiscoveryFrontier)
            .filter(
                DiscoveryFrontier.country_id == country_id,
                DiscoveryFrontier.url_hash == url_hash_value,
            )
            .first()
        )

    def _merge_observation(self, candidate: DiscoveryFrontier, observation: FrontierObservation | None) -> None:
        if observation is None:
            return
        evidence = dict(candidate.evidence or {})
        observations = list(evidence.get("observations", []))
        observations.append(observation.to_dict())
        evidence["observations"] = observations[-20:]  # bound evidence growth
        # Reassign (not mutate) so SQLAlchemy flags the JSONB column dirty
        candidate.evidence = evidence
        self.session.flush()

    # ------------------------------------------------------------------
    # Claiming (leases)
    # ------------------------------------------------------------------

    def claim_next(self, country_id, lease_seconds: int = 600) -> DiscoveryFrontier | None:
        """Atomically claim the next pending candidate via SKIP LOCKED.

        Also recovers stale IN_PROGRESS rows whose lease expired by returning
        them to PENDING state first.
        """
        now = datetime.now(timezone.utc)

        # Stale-lease recovery
        self.session.execute(
            text(
                """
                UPDATE discovery_frontier
                SET state = :pending, lease_expires_at = NULL
                WHERE state = :in_progress AND lease_expires_at < :now
                  AND country_id = :country_id
                """
            ),
            {
                "pending": FrontierState.PENDING,
                "in_progress": FrontierState.IN_PROGRESS,
                "now": now,
                "country_id": country_id,
            },
        )

        row = (
            self.session.query(DiscoveryFrontier)
            .filter(
                DiscoveryFrontier.country_id == country_id,
                DiscoveryFrontier.state == FrontierState.PENDING,
            )
            .order_by(DiscoveryFrontier.priority, DiscoveryFrontier.created_at)
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return None

        row.state = FrontierState.IN_PROGRESS
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        self.session.flush()
        return row

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def mark_done(self, candidate: DiscoveryFrontier, outcome: dict) -> None:
        candidate.state = FrontierState.DONE
        candidate.outcome = outcome
        candidate.processed_at = datetime.now(timezone.utc)
        candidate.lease_expires_at = None
        self.session.flush()

    def mark_rejected(self, candidate: DiscoveryFrontier, outcome: dict) -> None:
        candidate.state = FrontierState.REJECTED
        candidate.outcome = outcome
        candidate.processed_at = datetime.now(timezone.utc)
        candidate.lease_expires_at = None
        self.session.flush()

    def mark_deferred(self, candidate: DiscoveryFrontier, outcome: dict) -> None:
        candidate.state = FrontierState.DEFERRED
        candidate.outcome = outcome
        candidate.processed_at = datetime.now(timezone.utc)
        candidate.lease_expires_at = None
        self.session.flush()

    def mark_failed_transient(self, candidate: DiscoveryFrontier, error: str, max_retries: int) -> bool:
        """Record a transient failure; schedule retry or mark FAILED.

        Returns True if the candidate will be retried.
        """
        candidate.retry_count += 1
        outcome = dict(candidate.outcome or {})
        history = list(outcome.get("history", []))
        history.append({"event": "transient_error", "error": error[:500], "at": datetime.now(timezone.utc).isoformat()})
        outcome["history"] = history[-10:]
        candidate.outcome = outcome

        if candidate.retry_count >= max_retries:
            candidate.state = FrontierState.FAILED
            candidate.lease_expires_at = None
            candidate.processed_at = datetime.now(timezone.utc)
            self.session.flush()
            return False

        backoff = min(2 ** candidate.retry_count * 60, 3600)  # 2m, 4m, 8m … capped 1h
        candidate.state = FrontierState.PENDING
        candidate.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff)
        candidate.lease_expires_at = None
        self.session.flush()
        return True

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------

    def count_by_state(self, country_id) -> dict[str, int]:
        rows = (
            self.session.query(DiscoveryFrontier.state, text("count(*)"))
            .filter(DiscoveryFrontier.country_id == country_id)
            .group_by(DiscoveryFrontier.state)
            .all()
        )
        return {state: int(count) for state, count in rows}

    def count_pending(self, country_id) -> int:
        return (
            self.session.query(DiscoveryFrontier)
            .filter(
                DiscoveryFrontier.country_id == country_id,
                DiscoveryFrontier.state == FrontierState.PENDING,
            )
            .count()
        )
