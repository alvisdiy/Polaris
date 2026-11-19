"""Execute the complete extraction pipeline flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from services.ingestion.cleaner import CleanedDocument, clean
from services.ingestion.extractor import (
    ExtractedDocument,
    ExtractedScholarship,
    LLMClient,
)
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


def _invoke_client(llm_client: LLMClient, cleaned: CleanedDocument) -> ExtractedDocument:
    """Call the extraction client with as much page context as it accepts."""
    try:
        raw = llm_client.extract_scholarship(
            cleaned.clean_text,
            cleaned.source_url,
            page_title=cleaned.page_title,
            headings=tuple(cleaned.headings),
            anchors=tuple(cleaned.anchors),
            anchor_links=tuple({"text": link.text, "href": link.href} for link in cleaned.anchor_links),
            looks_like_index=cleaned.looks_like_index,
        )
    except TypeError:
        # Legacy client signature — keep it working rather than forcing every
        # client to grow the context parameters on the same commit.
        raw = llm_client.extract_scholarship(cleaned.clean_text, cleaned.source_url)
    return _as_document(cleaned, raw)


def _as_document(cleaned: CleanedDocument, raw) -> ExtractedDocument:
    """Wrap a client payload, stripping extractor-only metadata keys."""
    if isinstance(raw, ExtractedDocument):
        return raw
    payload = dict(raw or {})
    meta = payload.pop("_extraction", None)
    try:
        scholarship = ExtractedScholarship(**payload)
    except Exception as exc:  # noqa: BLE001 — surfaced as a validation failure
        return ExtractedDocument(
            document_id=cleaned.document_id,
            source_url=cleaned.source_url,
            error=str(exc),
        )
    if meta:
        scholarship = scholarship.model_copy(update={"extraction_meta": meta})
    return ExtractedDocument(
        document_id=cleaned.document_id,
        source_url=cleaned.source_url,
        scholarship=scholarship,
    )


def run_pipeline(document_id: str, session: Session, llm_client: LLMClient) -> PipelineResult:
    """Run the complete pipeline from RawDocument ID to validated JSON output."""
    # 1. Load from DB
    loaded = load(document_id, session)

    # 2. Clean
    cleaned = clean(loaded)

    # 3. Extract
    # DeterministicLLMClient consumes the cleaner's structural context
    # (title/headings/anchors) so name extraction can be judged on evidence
    # rather than on prose shape. Clients that do not accept it (the M8
    # signature) still work — they simply score lower.
    extracted = _invoke_client(llm_client, cleaned)

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
        document_url=raw_doc.source_url,
    )

    # Persist
    repo = ScholarshipRepository(session)
    return repo.save(scholarship)
