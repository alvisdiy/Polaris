"""Persistence-only repository for Scholarship entities."""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database.models.scholarship import Scholarship
from database.models.scholarship_degree_level import ScholarshipDegreeLevel
from services.review.publication import (
    public_filter,
    published_filter,
)
from services.scholarship.identity import (
    assess_duplicate,
    scholarship_identity_key,
)


class ScholarshipRepository:
    """Persistence layer for Scholarship. No business logic."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, scholarship: Scholarship) -> Scholarship:
        """Persist a Scholarship entity and return the canonical row.

        Deduplication lives here, not in the callers. Acquisition, the generic
        ingestion orchestrator and the seed scripts all reach persistence
        through this method; when dedup was a caller responsibility, any path
        that forgot it created a duplicate, and the only symptom was a row
        count that quietly grew.

        If a row already owns this canonical identity, that row is returned
        untouched and the incoming entity is discarded. No field of the
        existing row is written, so a later extraction can never overwrite an
        approved record or erase its provenance. Callers that intend a
        refresh — re-discovery, corrected extraction — must say so through
        :meth:`AcquisitionService._merge_reacquisition` or the candidate
        revision path, both of which record what changed.

        Raises:
            IdentityUnavailable: the entity has no usable name, so no identity
                can be derived. Persisting it would create a row permanently
                outside deduplication.
        """
        identity = scholarship_identity_key(
            scholarship.provider_id, scholarship.scholarship_name, scholarship.country_id
        )

        scholarship.identity_key = identity
        existing = assess_duplicate(
            self.session,
            canonical_key=identity,
            exclude_id=scholarship.scholarship_id,
        )
        if existing is not None:
            # Discard the incoming entity without writing anything. `pending`
            # covers a caller that added it before handing it over; `transient`
            # needs no cleanup, and expunging it is a no-op.
            if scholarship in self.session:
                self.session.expunge(scholarship)
            return existing

        self.session.add(scholarship)
        self.session.commit()
        self.session.refresh(scholarship)
        return scholarship

    def get_by_id(self, scholarship_id) -> Optional[Scholarship]:
        """Fetch a Scholarship by its scholarship_id, eager-loading children.

        NOT publication-filtered, on purpose. Review, admin and acquisition
        code must be able to reach a pending or rejected record; that is the
        whole point of a review queue. Public product reads use
        `get_published_by_id` instead, which applies the canonical predicate.
        """
        return self._by_id(scholarship_id).filter(
            Scholarship.scholarship_id == scholarship_id
        ).first()

    def get_published_by_id(self, scholarship_id) -> Optional[Scholarship]:
        """Fetch one scholarship only if it is publicly published.

        Returns None for a pending, rejected or needs-correction record, so a
        public caller gets the same answer the list endpoint would give rather
        than a record it has to remember to filter. Expiry is deliberately not
        part of this gate: an expired scholarship is still a published record,
        and 404ing its detail would break URLs the list already advertised.
        """
        return (
            self._by_id(scholarship_id)
            .filter(Scholarship.scholarship_id == scholarship_id, published_filter())
            .first()
        )

    def _by_id(self, scholarship_id):
        """The eager-loading query, shared so both read paths stay in step."""
        return self.session.query(Scholarship).options(
            joinedload(Scholarship.requirement),
            joinedload(Scholarship.benefit),
            joinedload(Scholarship.timeline),
            joinedload(Scholarship.versions),
            joinedload(Scholarship.country),
            joinedload(Scholarship.provider),
            joinedload(Scholarship.source),
        )

    def get_all_approved(self) -> list[Scholarship]:
        """Fetch all approved scholarships with children eager-loaded.

        Expired rows are excluded at query time (time-dependent constraint,
        per filtering-engine design review). Unclassified (NULL) rows stay
        visible — hiding them would silently drop legacy data.
        """
        return (
            self.session.query(Scholarship)
            .options(
                joinedload(Scholarship.requirement),
                joinedload(Scholarship.benefit),
                joinedload(Scholarship.timeline),
                joinedload(Scholarship.country),
                joinedload(Scholarship.provider),
            )
            .filter(public_filter())
            .all()
        )

    def reclassify_deadline_states(self, today=None) -> int:
        """Recompute deadline_state for every scholarship (freshness sweep).

        classification only — never touches timeline values. Rolling detection
        needs page text the repository does not hold, so rows keep their
        'rolling' state once earned and the sweep only re-evaluates the
        date-comparable states (active/expired/unknown).
        """
        from services.scholarship.freshness import (
            STATE_ROLLING,
            classify_deadline,
        )

        reference = today or date.today()
        changed = 0
        rows = self.session.query(Scholarship).options(joinedload(Scholarship.timeline)).all()
        for s in rows:
            if s.deadline_state == STATE_ROLLING:
                continue
            deadline = s.timeline.application_deadline if s.timeline else None
            new_state = classify_deadline(deadline, today=reference)
            if s.deadline_state != new_state:
                s.deadline_state = new_state
                changed += 1
        self.session.commit()
        return changed

    def get_currently_active(self, today=None) -> list[Scholarship]:
        """Approved scholarships whose deadline state is current.

        'unknown' is retained (source validity is judged elsewhere); only
        'expired' is excluded — per filtering-engine review: expired is
        objectively non-actionable.
        """
        return (
            self.session.query(Scholarship)
            .options(
                joinedload(Scholarship.requirement),
                joinedload(Scholarship.benefit),
                joinedload(Scholarship.timeline),
                joinedload(Scholarship.country),
                joinedload(Scholarship.provider),
            )
            .filter(
                published_filter(),
                Scholarship.deadline_state.in_(["active", "rolling", "unknown"]),
            )
            .all()
        )

    def find_duplicate(
        self,
        scholarship_name: str,
        provider_id,
        application_cycle: str | None,
        source_id,
    ) -> Optional[Scholarship]:
        """Detect duplicates using the deterministic rule from ADR-015.

        Duplicate = same name + same provider + same cycle + same source.
        application_cycle NULL is treated as a distinct value (NULL != NULL).
        """
        query = self.session.query(Scholarship).filter(
            Scholarship.scholarship_name == scholarship_name,
            Scholarship.provider_id == provider_id,
            Scholarship.source_id == source_id,
        )
        # application_cycle now lives on ScholarshipTimeline
        from database.models.scholarship_timeline import ScholarshipTimeline

        if application_cycle is None:
            query = query.join(ScholarshipTimeline).filter(ScholarshipTimeline.application_cycle.is_(None))
        else:
            query = query.join(ScholarshipTimeline).filter(ScholarshipTimeline.application_cycle == application_cycle)

        return query.first()

    def search_approved(
        self,
        query: str | None = None,
        country: str | None = None,
        degree: str | None = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[list[Scholarship], int]:
        """Search approved scholarships with pagination and filters.

        Expired scholarships are excluded (objectively non-actionable);
        deadline_state NULL (unclassified) remains visible.
        """
        from sqlalchemy import or_
        q = self.session.query(Scholarship).filter(public_filter())

        if query:
            q = q.filter(Scholarship.scholarship_name.ilike(f"%{query}%"))

        if country:
            # Check country name or iso3
            from database.models.country import Country
            q = q.join(Scholarship.country).filter(
                or_(Country.name.ilike(f"%{country}%"), Country.iso3.ilike(country))
            )

        if degree:
            # A record's level can live in the column or in its level rows. A
            # filter that only read the column would hide every multi-level
            # programme from the student filtering on their own level, which is
            # exactly the population the rows were added for.
            q = q.filter(
                or_(
                    Scholarship.degree.ilike(degree),
                    Scholarship.scholarship_id.in_(
                        select(ScholarshipDegreeLevel.scholarship_id).where(
                            ScholarshipDegreeLevel.degree.ilike(degree)
                        )
                    ),
                )
            )

        total = q.count()
        results = q.options(
            joinedload(Scholarship.timeline),
            joinedload(Scholarship.country),
            joinedload(Scholarship.provider),
        ).order_by(Scholarship.scholarship_name).limit(limit).offset(offset).all()

        return results, total

    def update(self, scholarship: Scholarship) -> Scholarship:
        """Commit changes to an already-attached Scholarship entity."""
        self.session.commit()
        self.session.refresh(scholarship)
        return scholarship
