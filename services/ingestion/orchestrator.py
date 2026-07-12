"""Execute the complete extraction pipeline flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from services.ingestion.cleaner import clean
from services.ingestion.extractor import ExtractedDocument, LLMClient, extract
from services.ingestion.loader import load
from services.ingestion.repositories import RawDocumentRepository
from services.ingestion.validator import ValidationReport, validate

if TYPE_CHECKING:
    from database.models.scholarship import Scholarship


class PipelineResult(BaseModel):
    """Encapsulates the output of a pipeline run."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    source_url: str
    is_valid: bool
    extracted_data: Dict[str, Any] | None
    validation_report: ValidationReport
    raw_extraction: ExtractedDocument


def run_pipeline(document_id: str, session: Session, llm_client: LLMClient) -> PipelineResult:
    """Run the complete pipeline from RawDocument ID to validated JSON output."""
    # 1. Load from DB
    loaded = load(document_id, session)

    # 2. Clean
    cleaned = clean(loaded)

    # 3. Extract
    extracted = extract(cleaned, llm_client)

    # 4. Validate
    report = validate(extracted)

    extracted_dict = None
    if report.is_valid and extracted.scholarship:
        extracted_dict = extracted.scholarship.model_dump()

    return PipelineResult(
        document_id=loaded.document_id,
        source_url=loaded.source_url,
        is_valid=report.is_valid,
        extracted_data=extracted_dict,
        validation_report=report,
        raw_extraction=extracted,
    )


def persist_scholarship(
    result: PipelineResult,
    document_id: str,
    session: Session,
) -> "Scholarship | None":
    """Persist a validated extraction into the Scholarship table.

    Only persists if the pipeline result is valid and contains extraction
    data. Returns the saved Scholarship entity, or None if validation
    failed.
    """
    from services.scholarship import ScholarshipMapper, ScholarshipRepository

    if not result.is_valid or result.raw_extraction.scholarship is None:
        return None

    # Resolve source_id from the RawDocument
    raw_doc_repo = RawDocumentRepository(session)
    raw_doc = raw_doc_repo.get_by_id(document_id)
    if raw_doc is None:
        raise ValueError(f"RawDocument not found: {document_id}")

    # Map extracted data to ORM entity
    mapper = ScholarshipMapper(session)
    scholarship = mapper.to_orm(
        extracted=result.raw_extraction.scholarship,
        source_id=str(raw_doc.source_id),
    )

    # Persist
    repo = ScholarshipRepository(session)
    return repo.save(scholarship)
