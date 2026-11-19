"""Lightweight registration of scholarship sources.

Enables direct registration of known scholarship sources without requiring
provider discovery as a prerequisite. Provider records are created automatically
with verification_status="unverified" when registering a source.
"""

import uuid
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from database.models.country import Country
from database.models.provider import Provider
from database.models.source_registry import SourceRegistry
from services.domain.lifecycle import (
    PROVIDER_DISCOVERED,
    SOURCE_ACTIVE,
    normalize_source_status,
)


def _normalize_domain(url: str) -> str:
    """Normalize URL to provider_code (domain with dots replaced by dashes).

    Args:
        url: Full URL or domain

    Returns:
        Normalized provider_code (e.g., "studyinjapan-go-jp")
    """
    parsed = urlparse(url if url.lower().startswith("http") else f"https://{url}")
    domain = parsed.netloc or parsed.path
    # Remove www. prefix if present
    if domain.lower().startswith("www."):
        domain = domain[4:]
    # Replace dots and slashes with dashes
    provider_code = domain.replace(".", "-").replace("/", "-").strip("-")
    return provider_code.lower()


def _get_or_create_provider(
    provider_code: str,
    provider_name: str,
    provider_type: str,
    country_id: uuid.UUID,
    session: Session,
    official_url: str | None = None,
) -> Provider:
    """Get existing Provider by code or create new one.

    Args:
        provider_code: Normalized domain identifier
        provider_name: Human-readable provider name
        provider_type: GOVERNMENT, UNIVERSITY, FOUNDATION, NGO, COMPANY
        country_id: Country where provider is located
        session: Database session

    Returns:
        Provider instance (existing or newly created)
    """
    # Check if provider already exists
    existing = session.query(Provider).filter(Provider.provider_code == provider_code).first()
    if existing:
        # A legacy row may still carry the old "unverified" spelling. Normalise
        # it on the way out so the next query sees a lifecycle state the rest of
        # the system recognises.
        if existing.verification_status == "unverified":
            existing.verification_status = PROVIDER_DISCOVERED
        # A provider created before this field was populated has no official
        # URL, which makes the coverage orchestrator skip it. The source that
        # registered it knows the URL; write it here.
        if not existing.official_url and official_url:
            existing.official_url = official_url
        return existing

    # Create new provider with the canonical discovered state
    provider = Provider(
        provider_id=uuid.uuid4(),
        provider_code=provider_code,
        provider_name=provider_name,
        provider_type=provider_type,
        country_id=country_id,
        verification_status=PROVIDER_DISCOVERED,  # Lifecycle starts here; verify later
        official_url=official_url,
    )
    session.add(provider)
    session.flush()  # Get provider_id without committing
    return provider


def register_source(
    country_iso2: str,
    official_url: str,
    provider_name: str,
    provider_type: str,
    session: Session,
    crawl_entry_url: Optional[str] = None,
    connector_name: str = "generic_http",
    crawl_method: str = "html_extraction",
    status: str = SOURCE_ACTIVE,
    source_name: Optional[str] = None,
) -> tuple[Provider, SourceRegistry]:
    """Register a scholarship source, creating Provider if needed.

    This is the primary entry point for adding known scholarship sources to Polaris.
    It creates both Provider and SourceRegistry records in a single operation.

    Args:
        country_iso2: Two-letter country code (e.g., "JP", "DE")
        official_url: The authoritative URL for this source
        provider_name: Human-readable name of the publishing organization
        provider_type: Organization type (GOVERNMENT, UNIVERSITY, FOUNDATION, NGO, COMPANY)
        session: Database session
        crawl_entry_url: Optional starting URL for crawling (defaults to official_url)
        connector_name: Connector class to use (default: "generic_http")
        crawl_method: Extraction method (default: "html_extraction")
        status: Source status (default: "active")
        source_name: Optional source name (defaults to provider_name + " Scholarship Portal")

    Returns:
        Tuple of (Provider, SourceRegistry)

    Raises:
        ValueError: If country not found or invalid parameters

    Example:
        >>> provider, source = register_source(
        ...     country_iso2="JP",
        ...     official_url="https://www.studyinjapan.go.jp/en/",
        ...     provider_name="MEXT - Ministry of Education",
        ...     provider_type="GOVERNMENT",
        ...     connector_name="mext_connector",
        ...     session=session,
        ... )
    """
    # 1. Get country
    country = session.query(Country).filter(Country.iso2 == country_iso2.upper()).first()
    if not country:
        raise ValueError(f"Country not found: {country_iso2}")

    # 2. Normalize domain to provider_code
    provider_code = _normalize_domain(official_url)

    # 3. Get or create Provider (lightweight, verification_status="unverified")
    provider = _get_or_create_provider(
        provider_code=provider_code,
        provider_name=provider_name,
        provider_type=provider_type,
        country_id=country.country_id,
        session=session,
        official_url=official_url,
    )

    # 4. Create SourceRegistry entry
    source = SourceRegistry(
        source_id=uuid.uuid4(),
        source_name=source_name or f"{provider_name} Scholarship Portal",
        country_id=country.country_id,
        provider_id=provider.provider_id,
        official_url=official_url,
        crawl_entry_url=crawl_entry_url or official_url,
        crawl_method=crawl_method,
        connector_name=connector_name,
        status=normalize_source_status(status),
        crawl_frequency="weekly",
        priority=5,
        robots_allowed=True,
        requires_login=False,
    )
    session.add(source)
    session.commit()

    return provider, source
