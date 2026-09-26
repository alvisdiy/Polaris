"""Persistence-only repository for Scholarship entities."""

from __future__ import annotations

from datetime import date
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import Session, joinedload

from database.models.scholarship import Scholarship


class ScholarshipRepository:
    """Persistence layer for Scholarship. No business logic."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, scholarship: Scholarship) -> Scholarship:
        """Persist a Scholarship entity (with children) and return the refreshed instance."""
        self.session.add(scholarship)
        self.session.commit()
        self.session.refresh(scholarship)
        return scholarship

    def get_by_id(self, scholarship_id) -> Optional[Scholarship]:
        """Fetch a Scholarship by its scholarship_id, eager-loading children."""
        return (
            self.session.query(Scholarship)
            .options(
                joinedload(Scholarship.requirement),
                joinedload(Scholarship.benefit),
                joinedload(Scholarship.timeline),
                joinedload(Scholarship.versions),
                joinedload(Scholarship.country),
                joinedload(Scholarship.provider),
                joinedload(Scholarship.source),
            )
            .filter(Scholarship.scholarship_id == scholarship_id)
            .first()
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
            .filter(
                Scholarship.extraction_status == "approved",
                sa.or_(
                    Scholarship.deadline_state.is_(None),
                    Scholarship.deadline_state != "expired",
                ),
            )
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
            STATE_ACTIVE,
            STATE_EXPIRED,
            STATE_ROLLING,
            STATE_UNKNOWN,
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
                Scholarship.extraction_status == "approved",
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
        q = self.session.query(Scholarship).filter(
            Scholarship.extraction_status == "approved",
            or_(
                Scholarship.deadline_state.is_(None),
                Scholarship.deadline_state != "expired",
            ),
        )
        
        if query:
            q = q.filter(Scholarship.scholarship_name.ilike(f"%{query}%"))
        
        if country:
            # Check country name or iso3
            from database.models.country import Country
            q = q.join(Scholarship.country).filter(
                or_(Country.name.ilike(f"%{country}%"), Country.iso3.ilike(country))
            )
            
        if degree:
            q = q.filter(Scholarship.degree.ilike(degree))
            
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
