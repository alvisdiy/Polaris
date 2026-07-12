"""Persistence-only repository for Scholarship entities."""

from __future__ import annotations

from typing import Optional

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
            )
            .filter(Scholarship.scholarship_id == scholarship_id)
            .first()
        )

    def get_all_approved(self) -> list[Scholarship]:
        """Fetch all approved scholarships with children eager-loaded."""
        return (
            self.session.query(Scholarship)
            .options(
                joinedload(Scholarship.requirement),
                joinedload(Scholarship.benefit),
                joinedload(Scholarship.timeline),
                joinedload(Scholarship.country),
                joinedload(Scholarship.provider),
            )
            .filter(Scholarship.extraction_status == "approved")
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

    def update(self, scholarship: Scholarship) -> Scholarship:
        """Commit changes to an already-attached Scholarship entity."""
        self.session.commit()
        self.session.refresh(scholarship)
        return scholarship
