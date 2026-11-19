"""Country Scholarship Ecosystem Discovery Orchestrator.

Given a country, discovers scholarship-relevant organizations (universities,
government programs, national scholarship agencies, foundations, research
institutions, and other legitimate organizations) by loading all enabled
ProviderDiscoveryConfig rows for that country and delegating to the
appropriate OrganizationDiscoveryStrategy implementations.

The orchestrator is intentionally thin and strategy-agnostic. It:
- Loads all enabled ProviderDiscoveryConfig rows for the country.
- Uses StrategyFactory to instantiate the appropriate strategy per config.
- Runs each strategy.
- Deduplicates discovered organizations by (country_id, normalized official_url).
- Persists each new/updated organization as a Provider row.
- Returns metrics.

Discovered organizations are always persisted with verification_status="candidate"
(or better, if a strategy supplies explicit evidence). Downstream source discovery
and the existing scholarship pipeline handle the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import or_

from database.models.enums import ProviderType
from database.models.provider import Provider
from services.exploration.url_utils import domain_of, registered_domain
from services.ingestion.ecosystem_strategies import (
    DiscoveredOrganization,
    OrganizationDiscoveryStrategy,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from database.models.country import Country


@dataclass
class EcosystemDiscoveryMetrics:
    """Metrics for a single country ecosystem discovery run."""

    country_iso2: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    strategies_executed: int = 0
    organizations_discovered: int = 0
    organizations_created: int = 0
    organizations_updated: int = 0
    duplicates_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "country_iso2": self.country_iso2,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "strategies_executed": self.strategies_executed,
            "organizations_discovered": self.organizations_discovered,
            "organizations_created": self.organizations_created,
            "organizations_updated": self.organizations_updated,
            "duplicates_skipped": self.duplicates_skipped,
            "errors": self.errors,
        }


def _normalize_url(url: str) -> str:
    """Return scheme://host/path for deduplication purposes."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or "/"
    return f"{parsed.scheme}://{host}{path}"


def _provider_code_from_url(url: str) -> str:
    """Derive a stable provider_code from the registered domain.

    Provider identity is the organization, not the path. The previous version
    hashed the full URL, so two links to the same university (homepage and
    admissions page) produced two Provider rows. One registered domain is one
    provider; its pages become sources.
    """
    host = domain_of(url)
    registered = registered_domain(host) or host
    return registered.replace(".", "_").upper()


class CountryEcosystemDiscovery:
    """Discovers the scholarship ecosystem for a single country."""

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.metrics: EcosystemDiscoveryMetrics | None = None

    async def discover(
        self,
        country: "Country",
        strategies: list[OrganizationDiscoveryStrategy],
    ) -> EcosystemDiscoveryMetrics:
        """Run ecosystem discovery for a country using the supplied strategies.

        Args:
            country: The Country record to discover organizations for.
            strategies: Non-empty list of OrganizationDiscoveryStrategy instances.

        Returns:
            EcosystemDiscoveryMetrics summarizing the run.
        """
        self.metrics = EcosystemDiscoveryMetrics(country_iso2=country.iso2)
        logger.info("Starting ecosystem discovery for {}", country.iso2)

        if not strategies:
            logger.warning("No strategies supplied for {}", country.iso2)
            return self._finalize()

        # Run every strategy and collect discovered organizations.
        all_discovered: list[DiscoveredOrganization] = []
        for strategy in strategies:
            try:
                discovered = await strategy.discover()
                self.metrics.strategies_executed += 1
                logger.info(
                    "Strategy {} discovered {} organizations for {}",
                    strategy.__class__.__name__,
                    len(discovered),
                    country.iso2,
                )
                all_discovered.extend(discovered)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Strategy {} failed for {}: {}",
                    strategy.__class__.__name__,
                    country.iso2,
                    exc,
                )
                self.metrics.errors.append(
                    f"{strategy.__class__.__name__}: {exc}"
                )

        self.metrics.organizations_discovered = len(all_discovered)

        # Deduplicate by normalized official URL within this run.
        seen: set[str] = set()
        unique_orgs: list[DiscoveredOrganization] = []
        for org in all_discovered:
            key = f"{org.country_id}::{_normalize_url(org.official_url)}"
            if key in seen:
                self.metrics.duplicates_skipped += 1
                continue
            seen.add(key)
            unique_orgs.append(org)

        # Persist organizations as Provider rows.
        for org in unique_orgs:
            try:
                await self._persist_organization(org)
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to persist organization {}: {}", org.name, exc)
                self.metrics.errors.append(f"Persist {org.name}: {exc}")

        return self._finalize()

    async def _persist_organization(self, org: DiscoveredOrganization) -> None:
        """Upsert a discovered organization into the Provider table."""
        provider_code = _provider_code_from_url(org.official_url)

        existing = (
            self.session.query(Provider)
            .filter(
                or_(
                    Provider.provider_code == provider_code,
                    Provider.official_url == org.official_url,
                )
            )
            .first()
        )

        if existing:
            # Preserve any existing verification status; only enrich provenance
            # if it was missing. Never downgrade verified providers to candidate.
            if not existing.discovery_source:
                existing.discovery_source = org.discovery_source
                existing.discovery_method = org.discovery_method
                existing.discovery_evidence = org.evidence
                existing.discovered_at = org.discovered_at
            self.metrics.organizations_updated += 1
        else:
            provider = Provider(
                provider_code=provider_code,
                provider_name=org.name,
                provider_type=ProviderType(org.organization_type),
                country_id=org.country_id,
                official_url=org.official_url,
                verification_status="candidate",
                discovery_source=org.discovery_source,
                discovery_method=org.discovery_method,
                discovery_evidence=org.evidence,
                discovered_at=org.discovered_at,
            )
            self.session.add(provider)
            self.metrics.organizations_created += 1

        self.session.flush()

    def _finalize(self) -> EcosystemDiscoveryMetrics:
        """Commit changes and finalize metrics."""
        try:
            self.session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to commit ecosystem discovery: {}", exc)
            self.session.rollback()
            self.metrics.errors.append(f"Commit failed: {exc}")

        self.metrics.finished_at = datetime.now(timezone.utc)
        duration = (self.metrics.finished_at - self.metrics.started_at).total_seconds()

        logger.info(
            "Ecosystem discovery for {} finished in {:.1f}s: "
            "discovered={}, created={}, updated={}, duplicates={}",
            self.metrics.country_iso2,
            duration,
            self.metrics.organizations_discovered,
            self.metrics.organizations_created,
            self.metrics.organizations_updated,
            self.metrics.duplicates_skipped,
        )
        return self.metrics
