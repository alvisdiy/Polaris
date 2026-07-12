"""Maps validated ExtractedScholarship data into a Scholarship ORM entity."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_benefit import ScholarshipBenefit
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.scholarship_timeline import ScholarshipTimeline
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
    the database or validate business rules.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def to_orm(
        self,
        extracted: ExtractedScholarship,
        source_id: str,
    ) -> Scholarship:
        """Map extracted data to a Scholarship ORM entity with children.

        Creates the Scholarship entity and its child entities:
        - ScholarshipRequirement (from eligibility)
        - ScholarshipBenefit (from benefits)
        - ScholarshipTimeline (from timeline)

        Args:
            extracted: Validated scholarship extraction from the LLM.
            source_id: UUID of the SourceRegistry entry.

        Returns:
            A transient (unsaved) Scholarship ORM entity with children attached.

        Raises:
            ValueError: If a required reference (provider, country) cannot
                be resolved from the database.
        """
        # Resolve reference entities
        provider = self._resolve_provider(extracted.provider_name)
        country = self._resolve_country(extracted.country)
        university = self._resolve_university(extracted.university)

        # Create parent entity
        scholarship = Scholarship(
            scholarship_name=extracted.scholarship_name,
            degree=extracted.degree,
            funding_type=extracted.funding_type,
            field_of_study=extracted.field_of_study,
            application_url=extracted.application_url,
            official_page_url=extracted.official_source,
            provider_id=provider.provider_id,
            country_id=country.country_id,
            university_id=university.university_id if university else None,
            source_id=source_id,
            extraction_status="pending_review",
        )

        # Create child: requirement
        elig = extracted.eligibility
        scholarship.requirement = ScholarshipRequirement(
            minimum_gpa=elig.minimum_gpa,
            ielts_required=elig.ielts_required or False,
            minimum_ielts=elig.minimum_ielts,
            toefl_required=elig.toefl_required or False,
            minimum_toefl=elig.minimum_toefl,
            gre_required=elig.gre_required or False,
            age_limit=elig.age_limit,
            work_experience=elig.work_experience,
            research_experience=elig.research_experience,
            publication=elig.publication,
            recommendation_letter=elig.recommendation_letter or False,
            motivation_letter=elig.motivation_letter or False,
            cv_required=elig.cv_required or False,
            passport_required=elig.passport_required or False,
        )

        # Create child: benefit
        ben = extracted.benefits
        scholarship.benefit = ScholarshipBenefit(
            tuition_fee=ben.tuition_fee,
            monthly_allowance=ben.monthly_allowance,
            accommodation=ben.accommodation,
            health_insurance=ben.health_insurance,
            travel_ticket=ben.travel_ticket,
            research_grant=ben.research_grant,
        )

        # Create child: timeline
        tl = extracted.timeline
        scholarship.timeline = ScholarshipTimeline(
            application_open=_parse_date(tl.application_open),
            application_deadline=_parse_date(tl.application_deadline),
            application_cycle=None,
            interview_date=_parse_date(tl.interview_date),
            result_date=_parse_date(tl.result_date),
            study_start=_parse_date(tl.study_start),
        )

        return scholarship

    # ------------------------------------------------------------------
    # Reference lookups
    # ------------------------------------------------------------------

    def _resolve_provider(self, provider_name: str) -> Provider:
        """Look up a Provider by exact name match."""
        provider = self._session.query(Provider).filter(Provider.provider_name == provider_name).first()
        if provider is None:
            raise ValueError(f"Provider not found: '{provider_name}'. Ensure the provider is seeded before mapping.")
        return provider

    def _resolve_country(self, country_name: str) -> Country:
        """Look up a Country by exact name match."""
        country = self._session.query(Country).filter(Country.name == country_name).first()
        if country is None:
            raise ValueError(f"Country not found: '{country_name}'. Ensure the country is seeded before mapping.")
        return country

    def _resolve_university(self, university_name: str | None) -> University | None:
        """Look up a University by exact name match. Returns None if not provided."""
        if university_name is None:
            return None
        return self._session.query(University).filter(University.name == university_name).first()
