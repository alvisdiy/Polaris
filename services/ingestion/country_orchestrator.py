"""Country-centric discovery orchestrator (legacy).

Kept for ``scripts/run_global_acquisition.py`` and historical tooling. New
per-country work goes through ``services.exploration.engine``, which owns page
intent, acquisition policy, aggregator blocking and the review boundary. This
path still uses the older ``DiscoveryOrchestrator`` and is therefore marked
legacy: fixing a precision bug in two places is how the two paths drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import func

from database.models.source_registry import SourceRegistry
from services.domain.source_trust import is_blocked_source_host
from services.ingestion.connectors import MEXTConnector
from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.generic_connector import GenericHTTPConnector
from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector
from services.ingestion.discovery import DiscoveryMetrics, DiscoveryOrchestrator

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# Connector dispatch: named connectors (legacy) + generic_http + generic_playwright
_CONNECTOR_MAP: dict[str, type] = {
    "mext_connector": MEXTConnector,
    "generic_http": GenericHTTPConnector,
    "generic_playwright": GenericPlaywrightConnector,
}


@dataclass
class CountryDiscoveryReport:
    """Aggregated discovery results across all sources in a country."""

    country_iso2: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    total_sources: int = 0
    sources_processed: int = 0
    total_candidates: int = 0
    total_fetched: int = 0
    total_persisted: int = 0
    total_duplicates: int = 0
    total_errors: int = 0
    per_source_metrics: dict[str, DiscoveryMetrics] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "country_iso2": self.country_iso2,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_sources": self.total_sources,
            "sources_processed": self.sources_processed,
            "total_candidates": self.total_candidates,
            "total_fetched": self.total_fetched,
            "total_persisted": self.total_persisted,
            "total_duplicates": self.total_duplicates,
            "total_errors": self.total_errors,
            "per_source_metrics": {
                name: metrics.to_dict()
                for name, metrics in self.per_source_metrics.items()
            },
            "errors": self.errors,
        }


class CountryDiscoveryOrchestrator:
    """Orchestrates discovery across all sources in a country."""

    def __init__(self, country_iso2: str, session: Session) -> None:
        self.country_iso2 = country_iso2
        self.session = session
        self.report = CountryDiscoveryReport(country_iso2=country_iso2)

    async def discover_all_sources(self, max_urls_per_source: int = 50) -> CountryDiscoveryReport:
        """Run discovery on all active sources for the country.

        Args:
            max_urls_per_source: Max URLs to process per source.

        Returns:
            CountryDiscoveryReport with aggregated metrics.
        """
        logger.info("Starting country discovery for country_iso2={}", self.country_iso2)

        try:
            # Query all active sources for this country
            from database.models.country import Country

            sources = (
                self.session.query(SourceRegistry)
                .join(Country)
                .filter(
                    Country.iso2 == self.country_iso2,
                    func.lower(SourceRegistry.status).in_(["active", "provisional"]),
                )
                .all()
            )

            self.report.total_sources = len(sources)
            logger.info("Found {} sources for {}", len(sources), self.country_iso2)

            if not sources:
                logger.info("No active sources found for {}", self.country_iso2)
                return self._finalize()

            # Process each source
            for source in sources:
                try:
                    await self._process_source(source, max_urls_per_source)
                except Exception as e:
                    logger.error("Error processing source {}: {}", source.source_id, e)
                    self.report.errors.append(f"{source.source_name}: {e}")

            return self._finalize()

        except Exception as e:
            logger.exception("Country discovery failed: {}", e)
            self.report.errors.append(str(e))
            return self._finalize()

    async def _process_source(self, source: SourceRegistry, max_urls: int) -> None:
        """Process a single source: discover and fetch URLs."""
        logger.info(
            "Processing source: {} (connector={})",
            source.source_name,
            source.connector_name,
        )

        # Choose the connector: an explicit connector name wins; a Playwright
        # crawl method selects the Playwright connector when no name is set.
        entry_url = source.crawl_entry_url or source.official_url
        if not entry_url:
            self.report.errors.append(
                f"{source.source_name}: no crawl_entry_url or official_url"
            )
            return
        if is_blocked_source_host(entry_url):
            self.report.errors.append(
                f"{source.source_name}: aggregator/social host is not an official source"
            )
            return

        if source.crawl_method == "Playwright":
            connector_class = _CONNECTOR_MAP.get("generic_playwright")
        else:
            connector_class = _CONNECTOR_MAP.get(source.connector_name or "")
        if not connector_class:
            logger.warning("Unknown connector: {}", source.connector_name)
            self.report.errors.append(f"{source.source_name}: unknown connector {source.connector_name}")
            return

        # Create config and connector
        config = ConnectorConfig(
            source_id=source.source_id,
            url=entry_url,
            timeout=30,
            user_agent="PolarisBot/0.1 (scholarship research)",
        )

        connector = connector_class(config)

        try:
            # Connect
            await connector.connect()

            # Create discovery orchestrator
            disc_orch = DiscoveryOrchestrator(connector, self.session)

            # Run discovery and processing
            metrics = await disc_orch.discover_and_process(max_urls=max_urls)

            # Store metrics
            self.report.per_source_metrics[source.source_name] = metrics
            self.report.sources_processed += 1

            # Aggregate
            self.report.total_candidates += metrics.candidate_urls_found
            self.report.total_fetched += metrics.fetch_succeeded
            self.report.total_persisted += metrics.persisted
            self.report.total_duplicates += metrics.duplicates_skipped
            self.report.total_errors += len(metrics.errors)

            logger.info(
                "Source {} complete: {} candidates, {} fetched, {} persisted",
                source.source_name,
                metrics.candidate_urls_found,
                metrics.fetch_succeeded,
                metrics.persisted,
            )

        finally:
            await connector.close()

    def _finalize(self) -> CountryDiscoveryReport:
        """Mark discovery complete."""
        self.report.finished_at = datetime.now(timezone.utc)
        duration = (self.report.finished_at - self.report.started_at).total_seconds()
        logger.info(
            "Country discovery complete for {} in {:.1f}s: {} sources, {} candidates, {} persisted, {} errors",
            self.country_iso2,
            duration,
            self.report.sources_processed,
            self.report.total_candidates,
            self.report.total_persisted,
            self.report.total_errors,
        )
        return self.report
