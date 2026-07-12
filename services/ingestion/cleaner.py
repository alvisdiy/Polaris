"""Clean raw HTML into processable text using trafilatura."""

from pydantic import BaseModel, ConfigDict

from services.ingestion.loader import LoadedDocument


class CleanedDocument(BaseModel):
    """Cleaned text ready for LLM extraction."""
    model_config = ConfigDict(frozen=True)

    document_id: str
    source_id: str
    source_url: str
    content_type: str
    clean_text: str


def clean(doc: LoadedDocument) -> CleanedDocument:
    """Extract clean main content from raw HTML.

    Uses trafilatura for noise removal (scripts, nav, footer, ads).
    Falls back to raw_content for non-HTML types.
    """
    if doc.content_type == "html":
        import trafilatura

        text = trafilatura.extract(
            doc.raw_content,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        clean_text = text if text else ""
    else:
        clean_text = doc.raw_content

    return CleanedDocument(
        document_id=doc.document_id,
        source_id=doc.source_id,
        source_url=doc.source_url,
        content_type=doc.content_type,
        clean_text=clean_text,
    )
