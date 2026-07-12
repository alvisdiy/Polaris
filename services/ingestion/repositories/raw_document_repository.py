"""Persistence-only repository for RawDocument entities."""

from typing import Optional

from sqlalchemy.orm import Session

from database.models.raw_document import RawDocument


class RawDocumentRepository:
    """Persistence layer for RawDocument. No business logic."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, raw_doc: RawDocument) -> RawDocument:
        """Persist a RawDocument entity and return the refreshed instance."""
        self.session.add(raw_doc)
        self.session.commit()
        self.session.refresh(raw_doc)
        return raw_doc

    def get_by_id(self, document_id) -> Optional[RawDocument]:
        """Fetch a RawDocument by its document_id."""
        return self.session.query(RawDocument).filter(RawDocument.document_id == document_id).first()

    def get_by_source_and_checksum(self, source_id, checksum: str) -> Optional[RawDocument]:
        """Fetch a RawDocument by its source_id and checksum."""
        return self.session.query(RawDocument).filter(
            RawDocument.source_id == source_id,
            RawDocument.checksum == checksum
        ).first()
