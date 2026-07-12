"""Load RawDocument content from PostgreSQL for pipeline processing."""

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from services.ingestion.repositories import RawDocumentRepository


class LoadedDocument(BaseModel):
    """Document ready for cleaning."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    source_id: str
    source_url: str
    content_type: str
    raw_content: str


def load(document_id: str, session: Session) -> LoadedDocument:
    """Load a RawDocument from PostgreSQL by document_id."""
    repo = RawDocumentRepository(session)
    raw_doc = repo.get_by_id(document_id)
    if not raw_doc:
        raise ValueError(f"RawDocument not found: {document_id}")
    return LoadedDocument(
        document_id=str(raw_doc.document_id),
        source_id=str(raw_doc.source_id),
        source_url=raw_doc.source_url,
        content_type=raw_doc.content_type,
        raw_content=raw_doc.raw_content,
    )
