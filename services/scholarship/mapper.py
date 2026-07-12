"""Maps validated ExtractedScholarship data into a Scholarship ORM entity."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.source_registry import SourceRegistry
from database.models.university import University
from services.ingestion.extractor import ExtractedScholarship


def _parse_date(value: str | None) -> date | None:
    """Parse ISO date string to date object. Returns None if input is None."""
    if value is None:
        return None
    return date.fromisoformat(value)


class ScholarshipMapper:
    """Converts validated extraction data into a Scholarship ORM entity.

    The mapper performs only object transformation. It does NOT write to
    the database, validate business rules, or call LLM.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def to_orm(
        self,
        extracted: ExtractedScholarship,
        source_id: str,
    ) -> Scholarship:
        """Map extracted data to a Scholarship ORM entity.

        Args:
            extracted: Validated scholarship extraction from the LLM.
            source_id: UUID of the SourceRegistry entry that produced
                this extraction.

        Returns:
            A transient (unsaved) Scholarship ORM entity.

        Raises:
            ValueError: If a required reference (provider, country) cannot
                be resolved from the database.
        """
        # --- Resolve reference entities ---
        provider = self._resolve_provider(extracted.provider_name)
        country = self._resolve_country(extracted.country)
        university = self._resolve_university(extracted.university)

        # --- Map fields ---
        scholarship = Scholarship(
            scholarship_name=extracted.scholarship_name,
            degree=extracted.degree,
            funding_type=extracted.funding_type,
            field_of_study=extracted.field_of_study,
            application_url=extracted.application_url,
            official_page_url=extracted.official_source,
            application_open=_parse_date(extracted.timeline.application_open),
            application_deadline=_parse_date(extracted.timeline.application_deadline),
            application_cycle=None,  # Never inferred; only from extracted data
            provider_id=provider.provider_id,
            country_id=country.country_id,
            university_id=university.university_id if university else None,
            source_id=source_id,
            extraction_status="pending_review",
        )

        return scholarship

    # ------------------------------------------------------------------
    # Reference lookups
    # ------------------------------------------------------------------

    def _resolve_provider(self, provider_name: str) -> Provider:
        """Look up a Provider by exact name match."""
        provider = (
            self._session.query(Provider)
            .filter(Provider.provider_name == provider_name)
            .first()
        )
        if provider is None:
            raise ValueError(
                f"Provider not found: '{provider_name}'. "
                "Ensure the provider is seeded before mapping."
            )
        return provider

    def _resolve_country(self, country_name: str) -> Country:
        """Look up a Country by exact name match."""
        country = (
            self._session.query(Country)
            .filter(Country.name == country_name)
            .first()
        )
        if country is None:
            raise ValueError(
                f"Country not found: '{country_name}'. "
                "Ensure the country is seeded before mapping."
            )
        return country

    def _resolve_university(self, university_name: str | None) -> University | None:
        """Look up a University by exact name match. Returns None if not provided."""
        if university_name is None:
            return None
        return (
            self._session.query(University)
            .filter(University.name == university_name)
            .first()
        )
