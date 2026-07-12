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
    application_deadline: str | None = None
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
    """Structured scholarship data extracted by LLM."""
    model_config = ConfigDict(frozen=True)

    scholarship_name: str
    provider_name: str
    scholarship_type: str
    country: str
    university: str | None = None
    degree: str
    funding_type: str
    field_of_study: list[str] = Field(default_factory=list)
    application_url: str
    official_source: str
    timeline: "Timeline" = Field(default_factory=lambda: Timeline())
    eligibility: "Eligibility" = Field(default_factory=lambda: Eligibility())
    benefits: "Benefits" = Field(default_factory=lambda: Benefits())
    verification_status: str = "pending_review"


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
