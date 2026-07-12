import abc
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

# --- Exceptions ---

class ConnectorException(Exception):
    """Base exception for all connector errors."""
    def __init__(self, message: str, source_id: Optional[uuid.UUID] = None) -> None:
        super().__init__(message)
        self.source_id = source_id


class ConnectorTimeoutException(ConnectorException):
    """Raised when the crawler/fetcher times out."""
    pass


class ConnectorHTTPException(ConnectorException):
    """Raised when an HTTP error (e.g., 404, 403, 429) occurs."""
    def __init__(self, message: str, status_code: int, source_id: Optional[uuid.UUID] = None) -> None:
        super().__init__(message, source_id=source_id)
        self.status_code = status_code


class ConnectorSecurityException(ConnectorException):
    """Raised when SSL validation fails or certificate issue occurs."""
    pass


class ConnectorParsingException(ConnectorException):
    """Raised when basic preprocessing or extraction fails."""
    pass


class ConnectorRateLimitException(ConnectorHTTPException):
    """Raised on HTTP 429 Too Many Requests."""
    def __init__(self, message: str, retry_after: Optional[int] = None, source_id: Optional[uuid.UUID] = None) -> None:
        super().__init__(message, status_code=429, source_id=source_id)
        self.retry_after = retry_after


# --- Models ---

class ConnectorConfig(BaseModel):
    """Configuration for a specific connector task."""
    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    url: HttpUrl
    timeout: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=3, ge=0, le=10)
    backoff_factor: float = Field(default=2.0, ge=1.0)
    headers: Dict[str, str] = Field(default_factory=dict)
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    custom_settings: Dict[str, Any] = Field(default_factory=dict)


class FetchResult(BaseModel):
    """Result returned by a connector after successfully crawling a source."""
    model_config = ConfigDict(frozen=True)

    source_id: uuid.UUID
    raw_content: str
    content_type: str = Field(pattern="^(html|pdf|json|markdown)$")
    final_url: Optional[str] = None
    response_size: Optional[int] = Field(default=None, ge=0)
    encoding: Optional[str] = None
    status_code: Optional[int] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    crawl_duration_ms: Optional[int] = Field(default=None, ge=0)
    crawl_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processing_time_ms: float = Field(ge=0.0)
    retry_count: int = Field(ge=0)
    headers: Dict[str, str] = Field(default_factory=dict)


# --- Base Connector ---

class BaseConnector(abc.ABC):
    """Abstract base class that all Polaris connectors must implement."""

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config

    @abc.abstractmethod
    async def connect(self) -> None:
        """Initialize the connection (e.g., open browser, setup sessions)."""
        pass

    @abc.abstractmethod
    async def fetch(self) -> FetchResult:
        """Fetch raw content from the configured source URL."""
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        """Close connection and clean up resources (e.g., close browser/sessions)."""
        pass
