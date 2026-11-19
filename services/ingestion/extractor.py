"""Abstract LLM client and extraction logic."""

from __future__ import annotations

import abc
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field

from services.ingestion.cleaner import CleanedDocument

# --- Extraction Schema ---


class Timeline(BaseModel):
    model_config = ConfigDict(frozen=True)

    application_open: str | None = None
    application_deadline: str | None = None  # Optional: not all sources provide deadlines
    application_cycle: str | None = None  # Cohort label, e.g. "2027" or "AY2027/28" — NOT a date
    interview_date: str | None = None
    result_date: str | None = None
    study_start: str | None = None


class Eligibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum_gpa: float | None = None
    ielts_required: bool | None = None
    minimum_ielts: float | None = None
    toefl_required: bool | None = None
    minimum_toefl: int | None = None
    gre_required: bool | None = None
    age_limit: int | None = None
    work_experience: str | None = None
    research_experience: str | None = None
    publication: str | None = None
    recommendation_letter: bool | None = None
    motivation_letter: bool | None = None
    cv_required: bool | None = None
    passport_required: bool | None = None


class Benefits(BaseModel):
    model_config = ConfigDict(frozen=True)

    tuition_fee: bool = False
    monthly_allowance: bool = False
    accommodation: bool = False
    health_insurance: bool = False
    travel_ticket: bool = False
    research_grant: bool = False


class ExtractedScholarship(BaseModel):
    """Structured scholarship data extracted by LLM.

    This model is the *whole* surface the extractor is allowed to answer on.
    Anything a client returns that is not a field here is refused rather than
    dropped, because a silently discarded publication-state key would leave a
    record that reads as if the model had been trusted with a decision it has
    no authority over — the failure would be invisible.

    There is deliberately no review or publication field here (M10). The
    extractor's only output is facts about a scholarship; the review state is
    written by the mapper as ``pending_review`` and changed by the review
    service alone.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # M9: nullable. The extractor reports "I could not identify this
    # scholarship" as None, which routes the record to review. The M8
    # placeholder string ("Unknown Scholarship") was indistinguishable from
    # a real name once persisted, and 134 records carried it.
    scholarship_name: str | None = None
    # M10: nullable for the same reason as the name. A page that does not name
    # its provider gets None, not the string "Unknown" — a provider called
    # "Unknown" is indistinguishable from a real one once it reaches the
    # Provider table, exactly as "Unknown Scholarship" was in the name column.
    # The mapper resolves an unresolved provider from the SourceRegistry row,
    # which is genuine provenance rather than a guess.
    provider_name: str | None = None
    scholarship_type: str | None = None  # Optional: fallback to provider type if missing
    country: str | None = None  # Will be defaulted to ecosystem country if None
    university: str | None = None
    degree: str | None = None  # Optional: unknown degree allowed
    # A national database can state the award's levels as a set. Those are
    # recorded here instead of collapsing into one level or into NULL.
    degree_levels: list[str] = Field(default_factory=list)
    funding_type: str | None = None  # Optional: unknown funding type allowed
    field_of_study: list[str] = Field(default_factory=list)  # May be empty if not mentioned
    # These may be unknown when the page does not expose a clearly labelled
    # destination. The article itself is provenance, never a substitute URL.
    application_url: str | None = None
    official_source: str | None = None
    timeline: "Timeline" = Field(default_factory=lambda: Timeline())
    eligibility: "Eligibility" = Field(default_factory=lambda: Eligibility())
    benefits: "Benefits" = Field(default_factory=lambda: Benefits())
    # M9 extraction provenance, produced by the extractor and consumed by
    # the mapper/persistence layer. Never used to publish anything.
    extraction_meta: dict[str, Any] = Field(default_factory=dict)


class ExtractedDocument(BaseModel):
    """Extraction result with metadata."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    source_url: str
    scholarship: ExtractedScholarship | None = None
    error: str | None = None


# --- Abstract LLM Client ---


class LLMClient(abc.ABC):
    """Provider-agnostic interface for LLM calls."""

    @abc.abstractmethod
    def extract_scholarship(self, clean_text: str, source_url: str) -> Dict[str, Any]:
        """Send cleaned text to LLM, return raw JSON dict of scholarship fields."""
        ...


# --- Extraction Logic ---


def extract(doc: CleanedDocument, client: LLMClient) -> ExtractedDocument:
    """Extract structured scholarship data from cleaned text using LLM client."""
    try:
        raw = client.extract_scholarship(doc.clean_text, doc.source_url)
        scholarship = ExtractedScholarship(**raw)
        return ExtractedDocument(
            document_id=doc.document_id,
            source_url=doc.source_url,
            scholarship=scholarship,
        )
    except Exception as e:
        return ExtractedDocument(
            document_id=doc.document_id,
            source_url=doc.source_url,
            error=str(e),
        )
