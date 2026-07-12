"""Maps a FetchResult to an ORM RawDocument entity."""

import hashlib

from database.models.raw_document import RawDocument
from services.ingestion.connectors import FetchResult


class RawDocumentMapper:
    """Converts transport-level FetchResult into a RawDocument ORM entity."""

    def to_orm(self, result: FetchResult) -> RawDocument:
        content_bytes = result.raw_content.encode("utf-8")
        checksum = hashlib.sha256(content_bytes).hexdigest()

        source_url = result.final_url
        if not source_url:
            raise ValueError("FetchResult.final_url is required")

        return RawDocument(
            source_id=result.source_id,
            source_url=source_url,
            content_type=result.content_type,
            raw_content=result.raw_content,
            checksum=checksum,
            status_code=result.status_code,
            fetched_at=result.crawl_time,
            etag=result.etag,
            last_modified=result.last_modified,
            crawl_duration_ms=result.crawl_duration_ms,
            processing_status="pending",
        )
