"""Complete country coverage orchestrator.

Integrates Provider Discovery → Source Discovery → Scholarship Discovery.

Flow:
1. Provider Discovery: discover organizations in the country
2. Source Verification: verify discovered providers
3. Source Discovery: find official scholarship pages from verified providers
4. Scholarship Discovery: discover individual scholarships from sources
5. Acquisition: fetch, extract, validate, persist scholarships
6. Report: comprehensive coverage metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import func

from database.models.country import Country
from database.models.provider import Provider
from database.models.source_registry import SourceRegistry
from services.domain.source_trust import is_blocked_source_host
from services.ingestion.ecosystem_discovery import CountryEcosystemDiscovery

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class CountryCoverageMetrics:
    """Complete coverage metrics for a country."""

    country_iso2: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    # Provider Discovery
    providers_discovered: int = 0
    providers_verified: int = 0
    providers_pending_review: int = 0
    providers_rejected: int = 0

    # Source Discovery
    sources_discovered: int = 0
    sources_verified: int = 0
    sources_active: int = 0

    # Scholarship Discovery
    candidate_urls_found: int = 0
    pages_fetched: int = 0
    extraction_succeeded: int = 0
    extraction_failed: int = 0
    scholarships_persisted: int = 0
    duplicates_skipped: int = 0

    # Errors
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "country_iso2": self.country_iso2,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "providers_discovered": self.providers_discovered,
            "providers_verified": self.providers_verified,
            "providers_pending_review": self.providers_pending_review,
            "providers_rejected": self.providers_rejected,
            "sources_discovered": self.sources_discovered,
            "sources_verified": self.sources_verified,
            "sources_active": self.sources_active,
            "candidate_urls_found": self.candidate_urls_found,
            "pages_fetched": self.pages_fetched,
            "extraction_succeeded": self.extraction_succeeded,
            "extraction_failed": self.extraction_failed,
            "scholarships_persisted": self.scholarships_persisted,
            "duplicates_skipped": self.duplicates_skipped,
            "errors": self.errors,
        }


class CountryCoverageOrchestrator:
    """Orchestrates complete country coverage: providers → sources → scholarships."""

    def __init__(self, country_iso2: str, session: Session) -> None:
        self.country_iso2 = country_iso2.upper()
        self.session = session
        self.metrics = CountryCoverageMetrics(country_iso2=self.country_iso2)

    async def run_full_coverage(
        self,
        run_provider_discovery: bool = True,
        run_scholarship_discovery: bool = True,
        max_urls_per_source: int = 50,
        max_sources: int = 20,
    ) -> CountryCoverageMetrics:
        """Run complete country coverage pipeline.

        Args:
            run_provider_discovery: Whether to discover new providers
            run_scholarship_discovery: Whether to discover scholarships from sources
            max_urls_per_source: Max scholarship URLs to process per source

        Returns:
            CountryCoverageMetrics with full coverage results
        """
        logger.info("=== Starting Full Country Coverage for {} ===", self.country_iso2)

        try:
            country = self.session.query(Country).filter_by(iso2=self.country_iso2).first()
            if not country:
                self.metrics.errors.append(f"Country {self.country_iso2} not found")
                return self._finalize()

            if run_provider_discovery:
                await self._run_provider_discovery()

            await self._run_source_discovery()

            if run_scholarship_discovery:
                await self._run_scholarship_discovery(max_urls_per_source, max_sources)

            return self._finalize()

        except Exception as e:
            logger.exception("Country coverage failed: {}", e)
            self.metrics.errors.append(str(e))
            return self._finalize()

    async def _run_provider_discovery(self) -> None:
        """Phase 1: Discover and verify providers using ecosystem strategies.

        For the Phase 2 vertical slice, uses UniversityStrategy for CN.
        Future phases will add GovernmentStrategy, FoundationStrategy, etc.
        All strategies reuse the same CountryEcosystemDiscovery engine.
        """
        logger.info("[Phase 1] Ecosystem Discovery for {}", self.country_iso2)

        try:
            country = self.session.query(Country).filter_by(iso2=self.country_iso2).first()
            if not country:
                logger.error("Country {} not found", self.country_iso2)
                self.metrics.errors.append(f"Country {self.country_iso2} not found")
                return

            # Load every enabled discovery configuration for the country and
            # resolve each through the strategy factory. The previous version
            # hardcoded UniversityStrategy, so adding a government/foundation
            # config had no effect on the run.
            from database.models.provider_discovery_config import ProviderDiscoveryConfig
            from services.ingestion.strategy_factory import StrategyFactory

            configs = (
                self.session.query(ProviderDiscoveryConfig)
                .filter_by(country_id=country.country_id, is_active=True)
                .all()
            )
            if not configs:
                logger.warning("No active ProviderDiscoveryConfig for {}", self.country_iso2)
                return

            strategies = []
            for config in configs:
                try:
                    strategies.append(
                        StrategyFactory.get_strategy(
                            config.organization_type,
                            country,
                            config.discovery_surface_url,
                            config,
                        )
                    )
                except KeyError as exc:
                    logger.warning("Unsupported discovery config: {}", exc)
                    self.metrics.errors.append(str(exc))
            if not strategies:
                logger.warning("No runnable discovery strategy for {}", self.country_iso2)
                return

            # Run ecosystem discovery
            engine = CountryEcosystemDiscovery(self.session)
            ecosystem_metrics = await engine.discover(country, strategies=strategies)

            # Map metrics to country coverage metrics
            self.metrics.providers_discovered = ecosystem_metrics.organizations_discovered
            self.metrics.providers_verified = ecosystem_metrics.organizations_created
            self.metrics.providers_pending_review = 0  # All discovered go to "candidate" for now
            self.metrics.errors.extend(ecosystem_metrics.errors)

            logger.info(
                "Ecosystem Discovery complete: {} discovered, {} created, {} updated",
                ecosystem_metrics.organizations_discovered,
                ecosystem_metrics.organizations_created,
                ecosystem_metrics.organizations_updated,
            )

        except Exception as e:
            logger.exception("Ecosystem Discovery failed: {}", e)
            self.metrics.errors.append(f"Ecosystem Discovery: {e}")

    async def _run_source_discovery(self) -> None:
        """Phase 2: Create SourceRegistry entries from discovered providers.

        Creates sources for any discovered provider (candidate or verified).
        Candidate providers get provisional sources that allow scholarship
        discovery to run without blocking on manual verification.
        """
        logger.info("[Phase 2] Source Discovery from discovered providers")

        try:
            country = self.session.query(Country).filter_by(iso2=self.country_iso2).first()
            if not country:
                return

            # Create sources for ALL discovered providers, not just verified ones.
            # This allows downstream scholarship discovery to proceed even when
            # a provider is only "candidate" (pending human review).
            discovered_providers = (
                self.session.query(Provider)
                .filter(
                    Provider.country_id == country.country_id,
                    Provider.verification_status.in_(
                        ["discovered", "candidate", "verified", "unverified"]
                    ),
                )
                .all()
            )

            logger.info("Found {} discovered providers for {}", len(discovered_providers), self.country_iso2)

            for provider in discovered_providers:
                if not provider.official_url:
                    self.metrics.errors.append(
                        f"provider {provider.provider_code} has no official_url; skipped"
                    )
                    continue
                if is_blocked_source_host(provider.official_url):
                    self.metrics.errors.append(
                        f"provider {provider.provider_code} points at an aggregator/social host; skipped"
                    )
                    continue

                existing_source = (
                    self.session.query(SourceRegistry)
                    .filter(
                        (SourceRegistry.provider_id == provider.provider_id)
                        | (SourceRegistry.official_url == provider.official_url)
                        | (SourceRegistry.crawl_entry_url == provider.official_url)
                    )
                    .first()
                )

                if existing_source:
                    self.metrics.sources_discovered += 1
                    if existing_source.status.lower() in ("active", "provisional"):
                        self.metrics.sources_active += 1
                    continue

                # Determine source status based on provider verification
                # Verified providers get "Active" sources (trust established)
                # Candidate/discovered providers get "Provisional" sources
                # (usable for scholarship discovery but flagged for review)
                if provider.verification_status == "verified":
                    source_status = "Active"
                    self.metrics.sources_verified += 1
                    self.metrics.sources_active += 1
                else:
                    source_status = "Provisional"
                    # Still counts as active for discovery, but flag it
                    self.metrics.sources_active += 1

                source = SourceRegistry(
                    source_name=f"{provider.provider_name} - Official Page",
                    country_id=country.country_id,
                    provider_id=provider.provider_id,
                    official_url=provider.official_url,
                    crawl_entry_url=provider.official_url,
                    crawl_method="Playwright",
                    connector_name="generic_playwright",
                    crawl_frequency="Monthly",
                    priority=2,
                    robots_allowed=True,
                    requires_login=False,
                    status=source_status,
                )
                self.session.add(source)
                self.metrics.sources_discovered += 1

                logger.info(
                    "Created source: {} ({}) from provider {}",
                    source.source_name,
                    source_status,
                    provider.provider_code,
                )

            self.session.commit()

        except Exception as e:
            self.session.rollback()
            logger.error("Source Discovery failed: {}", e)
            self.metrics.errors.append(f"Source Discovery: {e}")

    async def _run_scholarship_discovery(self, max_urls_per_source: int, max_sources: int = 20) -> None:
        """Phase 3: Acquire programmes from the country's sources.

        Uses ``AcquisitionService`` — the same path as country exploration —
        instead of the legacy ``DiscoveryOrchestrator``. That means page intent,
        the listing guard, aggregator blocking and the review boundary all apply;
        the previous path fed every discovered URL straight into extraction.
        """
        logger.info("[Phase 3] Scholarship Acquisition")

        try:
            from services.exploration.acquisition_service import AcquisitionService

            country = self.session.query(Country).filter_by(iso2=self.country_iso2).first()
            if not country:
                return

            sources = (
                self.session.query(SourceRegistry)
                .filter(
                    SourceRegistry.country_id == country.country_id,
                    func.lower(SourceRegistry.status).in_(["active", "provisional"]),
                )
                .order_by(SourceRegistry.priority)
                .limit(max_sources)
                .all()
            )
            logger.info("Acquiring from {} source(s) for {}", len(sources), self.country_iso2)

            service = AcquisitionService(self.session)
            for source in sources:
                entry_url = source.crawl_entry_url or source.official_url
                if not entry_url or is_blocked_source_host(entry_url):
                    continue
                try:
                    acq = await service.acquire_from_source(
                        source, max_pages=max_urls_per_source
                    )
                except Exception as exc:  # noqa: BLE001 — one source must not stop the country
                    self.metrics.errors.append(f"{source.source_name}: {exc}"[:300])
                    continue

                self.metrics.candidate_urls_found += acq.scholarship_urls_found
                self.metrics.pages_fetched += acq.pages_fetched
                self.metrics.scholarships_persisted += acq.scholarships_persisted
                self.metrics.duplicates_skipped += acq.duplicates_collapsed
                self.metrics.extraction_succeeded += acq.extraction_succeeded
                self.metrics.extraction_failed += acq.extraction_failed
                self.metrics.errors.extend(acq.errors)

            logger.info(
                "Scholarship Acquisition complete: {} candidates, {} fetched, {} persisted",
                self.metrics.candidate_urls_found,
                self.metrics.pages_fetched,
                self.metrics.scholarships_persisted,
            )

        except Exception as e:
            logger.error("Scholarship Acquisition failed: {}", e)
            self.metrics.errors.append(f"Scholarship Acquisition: {e}")

    def _finalize(self) -> CountryCoverageMetrics:
        """Finalize and return metrics."""
        self.metrics.finished_at = datetime.now(timezone.utc)
        duration = (self.metrics.finished_at - self.metrics.started_at).total_seconds()

        logger.info("=" * 80)
        logger.info("COUNTRY COVERAGE COMPLETE: {}", self.country_iso2)
        logger.info("=" * 80)
        logger.info("Duration: {:.1f}s", duration)
        logger.info(
            "Providers: {} discovered, {} verified",
            self.metrics.providers_discovered,
            self.metrics.providers_verified,
        )
        logger.info("Sources: {} discovered, {} active", self.metrics.sources_discovered, self.metrics.sources_active)
        logger.info(
            "Scholarships: {} fetched, {} persisted",
            self.metrics.pages_fetched,
            self.metrics.scholarships_persisted,
        )
        if self.metrics.errors:
            logger.warning("Errors: {}", len(self.metrics.errors))
        logger.info("=" * 80)

        return self.metrics
