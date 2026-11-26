"""Maps validated ExtractedScholarship data into a Scholarship ORM entity."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from database.models.country import Country
from database.models.provider import Provider
from database.models.scholarship import Scholarship
from database.models.scholarship_benefit import ScholarshipBenefit
from database.models.scholarship_degree_level import ScholarshipDegreeLevel
from database.models.scholarship_requirement import ScholarshipRequirement
from database.models.scholarship_timeline import ScholarshipTimeline
from database.models.university import University
from services.domain.vocabulary import UNMAPPED_QUALIFICATION_NOTE
from services.ingestion.extractor import ExtractedScholarship

if TYPE_CHECKING:
    from database.models.source_registry import SourceRegistry

# Mirrors the degree note for the funding case. Kept here rather than in
# services.domain.vocabulary because it describes the funding taxonomy's
# limit, not a qualification the domain has no category for.
UNMAPPED_FUNDING_NOTE = (
    "The page states its cost coverage in words the funding vocabulary cannot "
    "represent. The field is left empty on purpose: the wording is evidence, "
    "not a value. A reviewer sets the canonical value."
)


def _parse_date(value: str | None) -> date | None:
    """Parse ISO date string to date object. Returns None if input is None."""
    if value is None:
        return None
    return date.fromisoformat(value)


def _record_source_terms(provenance: dict, scholarship, meta: dict) -> None:
    """Attach source terminology to provenance for normalized fields.

    Two distinct things are worth recording, and they are not the same:

    - ``source_value`` — the wording the page used, when normalisation changed
      it ("master's degree" -> "Master"). Answers "what did the source call
      this?", which the canonical value alone cannot.
    - ``unmapped_qualification`` — a qualification Polaris has no category for
      ("diploma"). Recorded with a NULL degree, so the reviewer sees why the
      field is empty instead of assuming extraction simply failed (ADR-016).
    """
    for field in ("degree", "funding_type"):
        entry = provenance.get(field)
        if entry is None:
            continue
        raw = (meta.get("source_terms") or {}).get(field)
        if raw and raw != getattr(scholarship, field, None):
            entry["source_value"] = raw

    unmapped = meta.get("unmapped_qualification")
    if unmapped:
        entry = provenance.get("degree")
        if entry is not None:
            entry["unmapped_qualification"] = unmapped
            entry["note"] = UNMAPPED_QUALIFICATION_NOTE

    # Funding coverage the vocabulary cannot represent. Same purpose as the
    # degree case above (ADR-018): a NULL funding_type next to the page's own
    # wording is a question for the reviewer, and a bare NULL is not.
    funding_statement = meta.get("unmapped_funding_statement")
    if funding_statement:
        entry = provenance.get("funding_type")
        if entry is not None:
            entry["unmapped_funding_statement"] = funding_statement
            entry["note"] = UNMAPPED_FUNDING_NOTE


def _attach_intra_page_conflict(scholarship, meta: dict) -> None:
    """Record a contradiction the page states about itself.

    Polaris already had a cross-source conflict mechanism (`scholarship
    .conflicts`, read by `services.review.quality._conflict_map`), but nothing
    wrote it, so a page that contradicted *itself* had nowhere to say so. The
    shape is unchanged; only the origin is new.

    A conflict the page resolved itself is kept on the record as provenance
    rather than written to ``conflicts``: it is evidence of a deadline that
    moved, not a disagreement still open.
    """
    conflict = meta.get("deadline_conflict")
    if not conflict:
        return
    entry = dict(conflict)
    if entry.get("resolved"):
        provenance = scholarship.field_provenance or {}
        deadline_entry = dict(provenance.get("application_deadline") or {})
        deadline_entry["superseded_deadlines"] = entry["values"]
        deadline_entry["note"] = (
            "The page stated more than one deadline and named the replacement. "
            "The stored value is the one the page supersedes."
        )
        provenance["application_deadline"] = deadline_entry
        scholarship.field_provenance = provenance
        return

    existing = list(scholarship.conflicts or [])
    entry["values"] = [{**value, "source_url": meta.get("source_url")} for value in entry["values"]]
    existing.append(entry)
    scholarship.conflicts = existing


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
        *,
        document_url: str | None = None,
    ) -> Scholarship:
        """Map extracted data to a Scholarship ORM entity with children.

        Creates the Scholarship entity and its child entities:
        - ScholarshipRequirement (from eligibility)
        - ScholarshipBenefit (from benefits)
        - ScholarshipTimeline (from timeline)

        Args:
            extracted: Validated scholarship extraction from the LLM.
            source_id: UUID of the SourceRegistry entry.
            document_url: URL of the page the facts were extracted from, used
                as the official page when the extractor found no labelled
                official link.

        Returns:
            A transient (unsaved) Scholarship ORM entity with children attached.

        Raises:
            ValueError: If a required reference (provider, country) cannot
                be resolved from the database, or neither an official page URL
                nor a document URL is available.
        """
        # Resolve source provenance first
        from database.models.source_registry import SourceRegistry

        source = self._session.query(SourceRegistry).filter(SourceRegistry.source_id == source_id).first()
        if source is None:
            raise ValueError(f"SourceRegistry not found for source_id: {source_id}")

        # Resolve reference entities (fallback to source provenance)
        provider = self._resolve_provider(extracted.provider_name, source)
        country = self._resolve_country(extracted.country, source)
        university = self._resolve_university(extracted.university)

        # Create parent entity
        meta = extracted.extraction_meta or {}
        name_verdict = meta.get("name_verdict") or {}
        # `official_page_url` is NOT NULL because every record must be traceable
        # to the page its facts came from. The extractor fills `official_source`
        # only when it finds a *labelled link*; a programme page that simply is
        # its own official page has no such anchor. Falling back to the document
        # URL keeps the row persistable and keeps provenance honest — the review
        # quality gate can still refuse a placeholder host. Without this
        # fallback the insert raised NotNullViolation mid-acquisition, which
        # aborted the whole source and left it in `pending` (observed live on a
        # Japan Foundation fellowship page).
        official_page_url = (extracted.official_source or "").strip() or (document_url or "").strip()
        if not official_page_url:
            raise ValueError(
                "Scholarship has neither an official page URL nor a document URL to fall back to"
            )
        scholarship = Scholarship(
            scholarship_name=extracted.scholarship_name,
            degree=extracted.degree,
            funding_type=extracted.funding_type,
            funding_amount=extracted.funding_amount,
            funding_currency=extracted.funding_currency,
            funding_period=extracted.funding_period,
            funding_duration_months=extracted.funding_duration_months,
            description=extracted.description,
            field_of_study=extracted.field_of_study,
            application_url=extracted.application_url,
            official_page_url=official_page_url,
            provider_id=provider.provider_id,
            country_id=country.country_id,
            university_id=university.university_id if university else None,
            source_id=source_id,
            extraction_status="pending_review",
            # The extractor's own confidence in the *name*, kept as evidence
            # for the reviewer rather than used to publish anything.
            extraction_confidence=name_verdict.get("confidence"),
            provenance_origin=meta.get("origin") or "unknown",
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

        # Create children: degree levels. Only when the page stated a set; a
        # single-level record keeps the column and writes no rows, so nothing
        # about the existing single-degree path changes.
        levels = [level for level in (extracted.degree_levels or []) if level]
        if levels and not extracted.degree:
            scholarship.degree_levels = [
                ScholarshipDegreeLevel(degree=level) for level in dict.fromkeys(levels)
            ]

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
            application_cycle=tl.application_cycle or None,
            interview_date=_parse_date(tl.interview_date),
            result_date=_parse_date(tl.result_date),
            study_start=_parse_date(tl.study_start),
        )

        self._attach_extraction_evidence(scholarship, meta, provider, country)
        _attach_intra_page_conflict(scholarship, meta)
        return scholarship

    # ------------------------------------------------------------------
    # Extraction evidence
    # ------------------------------------------------------------------

    def _attach_extraction_evidence(
        self,
        scholarship: Scholarship,
        meta: dict,
        provider: Provider,
        country: Country,
    ) -> None:
        """Record provenance and run the publication gates at extraction time.

        Two jobs, both about the reviewer rather than the pipeline:

        - ``field_provenance`` makes "where did this field come from?"
          answerable for every important field, which M9 principle 2 requires
          and M8 did not have at all.
        - ``quality_report`` is the gate result as of extraction, stored so a
          reviewer sees what was known when the record arrived. It is a
          snapshot, never a decision: the reviewer re-runs the gates, and
          approval re-evaluates them.

        The extractor's `name_verdict` is folded in so the report can explain
        why identity passed or failed rather than only that it did.
        """
        from services.review.quality import build_report

        stored = dict(meta.get("name_verdict") and {"name_verdict": meta["name_verdict"]} or {})
        # Persisted so the review-time gate can re-evaluate it: a country
        # inferred from the source must not pass as a stated fact, and the
        # flag has to survive from extraction to the reviewer's desk.
        stored["country_inferred_from_source"] = bool(
            meta.get("country_inferred_from_source")
        )
        stored["extracted_at"] = meta.get("extracted_at")
        stored["document_id"] = meta.get("document_id")
        stored["origin"] = meta.get("origin")
        stored["source_document_url"] = meta.get("source_url")
        stored["url_targets"] = {
            "article_url": meta.get("source_url"),
            "official_program_url": scholarship.official_page_url,
            "application_url": scholarship.application_url,
        }

        report = build_report(
            scholarship_name=scholarship.scholarship_name,
            name_verdict=meta.get("name_verdict"),
            provider_name=getattr(provider, "provider_name", None),
            country_name=getattr(country, "name", None),
            country_inferred=bool(meta.get("country_inferred_from_source")),
            official_page_url=scholarship.official_page_url,
            degree=scholarship.degree,
            funding_type=scholarship.funding_type,
            field_of_study=scholarship.field_of_study,
            deadline_present=scholarship.timeline is not None,
            application_deadline=scholarship.timeline.application_deadline,
            application_open=scholarship.timeline.application_open,
            application_cycle=scholarship.timeline.application_cycle,
            requirement=scholarship.requirement,
            benefit=scholarship.benefit,
            conflicts=scholarship.conflicts,
        )
        stored.update(report.to_dict())
        scholarship.quality_report = stored

        # The source URL is the document that made the claim. A URL extracted
        # from one of its anchors is a target value, not the evidence document.
        source_url = meta.get("source_url") or scholarship.official_page_url
        method = meta.get("method") or "deterministic_extractor"

        # Controlled fields are normalized from source wording, so the original
        # is recorded alongside the canonical value. Without this, "master's
        # degree" and "Ph.D." would both vanish into "Master"/"PhD" and there
        # would be no way to show a reviewer what the page actually said
        # (ADR-016, Phase 9).
        field_evidence = meta.get("field_evidence") or {}

        def evidence_for(name: str, parent: str | None = None) -> dict:
            evidence = field_evidence.get(name)
            if evidence is None and parent:
                evidence = (field_evidence.get(parent) or {}).get(name)
            evidence = evidence or {}
            return {
                "source_url": evidence.get("source_url") or source_url,
                "document_id": evidence.get("document_id") or meta.get("document_id"),
                "extracted_at": meta.get("extracted_at"),
                "confidence": (
                    (meta.get("name_verdict") or {}).get("confidence") if name == "scholarship_name" else None
                ),
                "method": method,
                "origin": evidence.get("origin") or "machine_extracted",
            }

        provenance = {
            "scholarship_name": evidence_for("scholarship_name"),
            "deadline": evidence_for("application_deadline", "timeline"),
            "degree": evidence_for("degree"),
            "funding_type": evidence_for("funding_type"),
            "funding_amount": evidence_for("funding_amount"),
            "eligibility": evidence_for("eligibility"),
        }
        provenance["official_page_url"] = {
            "source_url": source_url,
            "target_url": scholarship.official_page_url,
            "document_id": meta.get("document_id"),
            "target_document_id": meta.get("official_document_id"),
            "extracted_at": meta.get("extracted_at"),
            "method": method,
            "origin": "machine_extracted_link",
        }
        provenance["application_url"] = {
            "source_url": source_url,
            "target_url": scholarship.application_url,
            "document_id": meta.get("document_id"),
            "target_document_id": (field_evidence.get("application_url") or {}).get("document_id"),
            "extracted_at": meta.get("extracted_at"),
            "method": method,
            "origin": "machine_extracted_link",
        }
        amount_evidence = meta.get("funding_amount_evidence")
        if amount_evidence:
            provenance["funding_amount"]["statement"] = amount_evidence.get("statement")
        _record_source_terms(provenance, scholarship, meta)
        scholarship.field_provenance = provenance

    # ------------------------------------------------------------------
    # Reference lookups
    # ------------------------------------------------------------------

    def _resolve_provider(self, provider_name: str, source: "SourceRegistry | None" = None) -> Provider:
        """Look up a Provider by name, falling back to source provenance."""
        if provider_name:
            provider = self._session.query(Provider).filter(Provider.provider_name == provider_name).first()
            if provider:
                return provider
        # Fallback: use the source's provider
        if source and source.provider_id:
            provider = self._session.query(Provider).filter(Provider.provider_id == source.provider_id).first()
            if provider:
                return provider
        raise ValueError(f"Provider not found: '{provider_name}'. Ensure the provider is seeded before mapping.")

    def _resolve_country(self, country_name: str, source: "SourceRegistry | None" = None) -> Country:
        """Look up a Country by name, falling back to source provenance."""
        if country_name:
            country = self._session.query(Country).filter(Country.name == country_name).first()
            if country:
                return country
        # Fallback: use the source's country
        if source and source.country_id:
            country = self._session.query(Country).filter(Country.country_id == source.country_id).first()
            if country:
                return country
        raise ValueError(f"Country not found: '{country_name}'. Ensure the country is seeded before mapping.")

    def _resolve_university(self, university_name: str | None) -> University | None:
        """Look up a University by exact name match. Returns None if not provided."""
        if university_name is None:
            return None
        return self._session.query(University).filter(University.name == university_name).first()
