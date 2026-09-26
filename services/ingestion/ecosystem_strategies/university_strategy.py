"""University discovery strategy – first vertical slice.

For the proof‑of‑concept we implement a very simple link‑discovery strategy
that crawls a configurable discovery surface (e.g. a national university
directory) and extracts any URLs that look like official university domains.

The strategy **does not** enforce hard filters – TLDs, keywords, or URL
patterns are only used as relevance signals. All extracted URLs become
`DiscoveredOrganization` objects with `organization_type="University"`.

The implementation deliberately stays minimal; it can be replaced with a
more sophisticated crawler later without touching the orchestrator.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from loguru import logger

from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector
from services.ingestion.ecosystem_strategies import (
    DiscoveredOrganization,
    OrganizationDiscoveryStrategy,
)

if TYPE_CHECKING:
    from database.models.country import Country


class UniversityStrategy(OrganizationDiscoveryStrategy):
    """Simple university discovery for a country.

    The strategy expects a `ProviderDiscoveryConfig` row with
    `discovery_strategy == "link_discovery"` and a `discovery_surface_url`
    that lists universities (or a directory of educational institutions).

    It uses `GenericPlaywrightConnector` to fetch the page, extracts all
    `<a href>` links, normalises them, and returns them as `DiscoveredOrganization`
    objects. No hard gating – every link becomes a candidate; the orchestrator
    will later apply verification and deduplication.
    """

    def __init__(self, country: "Country", surface_url: str) -> None:
        super().__init__(country)
        self.surface_url = surface_url

    async def discover(self) -> list[DiscoveredOrganization]:
        logger.info(
            "UniversityStrategy: discovering universities for {} via {}",
            self.country.iso2,
            self.surface_url,
        )

        cfg = ConnectorConfig(
            source_id=uuid.uuid4(),
            url=self.surface_url,
            timeout=30,
            user_agent="PolarisBot/0.1 (university discovery)",
        )
        connector = GenericPlaywrightConnector(cfg)
        try:
            await connector.connect()
            raw_links = await connector.discover()  # Returns list of URLs
        finally:
            await connector.close()

        logger.info(
            "UniversityStrategy: extracted {} raw links for {}",
            len(raw_links),
            self.country.iso2,
        )

        discovered: list[DiscoveredOrganization] = []
        for link in raw_links:
            # We keep every link – relevance signals are optional.
            org = self._make_discovered(
                name=link,  # placeholder – later can be refined via page title
                org_type="University",
                url=link,
                source=self.surface_url,
                method="link_discovery",
                confidence=0.5,
                evidence={"origin": "link_discovery"},
            )
            discovered.append(org)

        logger.info(
            "UniversityStrategy: produced {} DiscoveredOrganization objects for {}",
            len(discovered),
            self.country.iso2,
        )
        return discovered
