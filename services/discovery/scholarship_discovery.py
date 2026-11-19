"""Country-level scholarship discovery orchestrator.

Discovers scholarship URLs from all registered sources for a country,
aggregating across multiple discovery channels (government portals,
universities, foundations, agencies, etc.).
"""

import asyncio
import importlib
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models.country import Country
from database.models.source_registry import SourceRegistry
from services.ingestion.connectors.base_connector import ConnectorConfig


def _instantiate_connector(connector_name: str, config: ConnectorConfig):
    """Dynamically instantiate a connector by name.

    Args:
        connector_name: Connector class name (e.g., "mext_connector", "generic_http")
        config: ConnectorConfig instance

    Returns:
        Instantiated connector instance

    Raises:
        ImportError: If connector not found
        ValueError: If connector instantiation fails
    """
    # Map connector names to module paths
    connector_map = {
        "mext_connector": ("services.ingestion.connectors.government.mext_connector", "MEXTConnector"),
        "generic_http": ("services.ingestion.connectors.generic_connector", "GenericHTTPConnector"),
        "generic_playwright": ("services.ingestion.connectors.generic_playwright", "GenericPlaywrightConnector"),
    }

    if connector_name not in connector_map:
        raise ValueError(f"Unknown connector: {connector_name}")

    module_path, class_name = connector_map[connector_name]
    try:
        module = importlib.import_module(module_path)
        connector_class = getattr(module, class_name)
        return connector_class(config)
    except (ImportError, AttributeError) as e:
        raise ImportError(f"Failed to load connector {connector_name}: {e}")


def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication (strip trailing slash, fragment).

    Args:
        url: Full URL

    Returns:
        Normalized URL
    """
    # Remove fragment
    if "#" in url:
        url = url.split("#")[0]
    # Remove trailing slash for comparison (but keep it for return)
    return url.rstrip("/")


async def _discover_from_source_async(source: SourceRegistry) -> list[dict]:
    """Discover scholarship URLs from a single source (async).

    Args:
        source: SourceRegistry entry

    Returns:
        List of dicts with URL and metadata
    """
    config = ConnectorConfig(
        source_id=source.source_id,
        url=source.crawl_entry_url,
        timeout=30,
        max_retries=2,
    )

    connector = _instantiate_connector(source.connector_name, config)

    try:
        await connector.connect()

        # Try discover_scholarship_urls first, fall back to discover
        discover_method = getattr(connector, "discover_scholarship_urls", None) or getattr(connector, "discover", None)
        if not discover_method:
            raise AttributeError(f"Connector {source.connector_name} has no discovery method")

        # Call async discover method
        if asyncio.iscoroutinefunction(discover_method):
            urls = await discover_method()
        else:
            urls = discover_method()

        return [
            {
                "url": url,
                "source_id": str(source.source_id),
                "source_name": source.source_name,
                "provider_name": source.provider.provider_name,
                "connector_name": source.connector_name,
            }
            for url in urls
        ]
    finally:
        await connector.close()


async def discover_scholarships_for_country_async(
    country_iso2: str,
    session: Session,
    limit: Optional[int] = None,
) -> list[dict]:
    """Discover scholarship URLs from all active sources for a country.

    This is the primary entry point for scholarship-first discovery.
    It loads all registered sources for a country and aggregates
    scholarship URLs from multiple channels.

    Args:
        country_iso2: Two-letter country code (e.g., "JP", "DE")
        session: Database session
        limit: Optional max number of URLs to return

    Returns:
        List of dicts with keys:
            - url: Scholarship detail page URL
            - source_id: UUID of SourceRegistry entry
            - source_name: Name of the source
            - provider_name: Name of the provider (publisher)
            - connector_name: Connector used to discover

    Raises:
        ValueError: If country not found

    Example:
        >>> scholarships = discover_scholarships_for_country("JP", session)
        >>> print(f"Discovered {len(scholarships)} scholarship URLs")
        >>> for s in scholarships[:3]:
        ...     print(f"  {s['url']} (from {s['source_name']})")
    """
    # 1. Get country
    country = session.query(Country).filter(Country.iso2 == country_iso2.upper()).first()
    if not country:
        raise ValueError(f"Country not found: {country_iso2}")

    # 2. Load active SourceRegistry entries for country
    sources = session.query(SourceRegistry).filter(
        SourceRegistry.country_id == country.country_id,
        func.lower(SourceRegistry.status) == "active",
    ).all()

    if not sources:
        return []

    # 3. For each source: call connector.discover() asynchronously
    discovered_urls = {}  # Use dict for deduplication: normalized_url -> full data

    async def discover_all():
        tasks = [_discover_from_source_async(source) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results

    results = await discover_all()

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"Warning: Failed to discover from {sources[i].source_name}: {result}")
            continue

        for item in result:
            url = item["url"]
            normalized = _normalize_url(url)
            if normalized not in discovered_urls:  # Deduplicate
                discovered_urls[normalized] = item

    # 4. Return list
    result = list(discovered_urls.values())
    if limit:
        result = result[:limit]

    return result


def discover_scholarships_for_country(
    country_iso2: str,
    session: Session,
    limit: Optional[int] = None,
) -> list[dict]:
    """Blocking wrapper around :func:`discover_scholarships_for_country_async`.

    The async form exists because ``asyncio.run`` — which this wrapper calls —
    raises when invoked from a caller that already owns an event loop. An
    operator script that is itself async must await the async form.
    """
    return asyncio.run(
        discover_scholarships_for_country_async(country_iso2, session, limit)
    )


def discover_scholarships_for_source(
    source_id: UUID,
    session: Session,
) -> list[dict]:
    """Discover scholarship URLs from a single source.

    Convenience method for discovering from a specific source.

    Args:
        source_id: UUID of SourceRegistry entry
        session: Database session

    Returns:
        List of dicts (same format as discover_scholarships_for_country)

    Raises:
        ValueError: If source not found
    """
    source = session.query(SourceRegistry).filter(SourceRegistry.source_id == source_id).first()
    if not source:
        raise ValueError(f"Source not found: {source_id}")

    try:
        results = asyncio.run(_discover_from_source_async(source))
        return results
    except Exception as e:
        raise ValueError(f"Failed to discover from source {source_id}: {e}")
