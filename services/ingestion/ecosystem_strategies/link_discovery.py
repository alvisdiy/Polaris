"""Link-discovery strategy for any organization type.

A discovery surface is an authoritative page that lists organizations: a
ministry's university directory, a scholarship agency's partner list, a
foundation's programme index. The strategy fetches that page, keeps links whose
registered domain matches the country's official TLDs, and emits one
``DiscoveredOrganization`` per domain.

The organization *type* is configuration, not code. ``UniversityStrategy`` is
kept as a thin subclass because existing callers import it, but Government,
Foundation and Scholarship Agency surfaces use the same mechanism with a
different label. That is the seam the provider-discovery specification asks
for: adding a country or a surface should be a config row, not a new crawler.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from loguru import logger

from services.domain.source_trust import is_blocked_source_host
from services.exploration.url_utils import domain_of, registered_domain
from services.ingestion.connectors.base_connector import ConnectorConfig
from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector
from services.ingestion.ecosystem_strategies import (
    DiscoveredOrganization,
    OrganizationDiscoveryStrategy,
)

if TYPE_CHECKING:
    from database.models.country import Country


#: Suffixes that identify a government host. Explicit per jurisdiction rather
#: than a loose ".go." test: "google." must not match.
_GOVERNMENT_SUFFIXES = (
    ".gov", ".gov.uk", ".gov.au", ".gov.sg", ".gov.cn", ".gov.hk",
    ".govt.nz", ".gc.ca", ".gouv.fr", ".go.jp", ".go.kr", ".go.id",
)

#: Suffixes that identify an academic host.
_ACADEMIC_SUFFIXES = (
    ".edu", ".ac.uk", ".ac.jp", ".ac.kr", ".ac.id", ".ac.in",
    ".edu.cn", ".edu.au", ".edu.sg", ".edu.hk", ".edu.my",
)

#: Non-profit suffixes. The specification says these require review, so they
#: are labelled NGO rather than promoted to a verified provider.
_NGO_SUFFIXES = (".org", ".or.jp", ".or.kr", ".or.id", ".org.uk", ".org.au")



class LinkDiscoveryStrategy(OrganizationDiscoveryStrategy):
    """Discover organizations of one configured type from a listing surface."""

    organization_type = "University"

    def __init__(
        self,
        country: "Country",
        surface_url: str,
        *,
        organization_type: str | None = None,
        allowed_tlds: list[str] | None = None,
        keyword_filters: list[str] | None = None,
    ) -> None:
        super().__init__(country)
        self.surface_url = surface_url
        self.organization_type = organization_type or self.organization_type
        self.allowed_tlds = [t.lower() for t in (allowed_tlds or [])]
        self.keyword_filters = [k.lower() for k in (keyword_filters or [])]

    def _allowed_url(self, url: str) -> bool:
        """Official TLD filter, plus the aggregator/social blocklist.

        TLD filtering is the specification's Check 1. The blocklist is not in
        the spec but is the same rule the rest of the product follows: a
        listing site or social platform is never an official provider.
        """
        if not url or is_blocked_source_host(url):
            return False
        if not self.allowed_tlds:
            return True
        host = domain_of(url)
        registered = registered_domain(host)
        return any(
            host.endswith(suffix) or registered.endswith(suffix)
            for suffix in self.allowed_tlds
        )

    @staticmethod
    def _domain(url: str) -> str:
        host = domain_of(url)
        return registered_domain(host) or host

    def _infer_type(self, url: str) -> str:
        """Infer the organization type from the host, per the spec's Check 4.

        A ministry page links to universities; labelling every link on it as
        "Government" would put a university in the wrong lifecycle and route it
        through the wrong review expectations. Suffix evidence wins; the
        surface's configured type is the fallback.
        """
        domain = self._domain(url)
        # The surface's own organization is the surface type: JASSO is a
        # scholarship agency even though it lives on .go.jp, and labelling it
        # "Government" would lose that distinction.
        if domain == self._domain(self.surface_url):
            return self.organization_type
        if any(domain.endswith(suffix) for suffix in _GOVERNMENT_SUFFIXES):
            return "Government"
        if any(domain.endswith(suffix) for suffix in _ACADEMIC_SUFFIXES):
            return "University"
        if "foundation" in domain or "stiftung" in domain:
            return "Foundation"
        if any(domain.endswith(suffix) for suffix in _NGO_SUFFIXES):
            return "NGO"
        return self.organization_type

    async def discover(self) -> list[DiscoveredOrganization]:
        logger.info(
            "{}: discovering {} organizations for {} via {}",
            self.__class__.__name__,
            self.organization_type,
            self.country.iso2,
            self.surface_url,
        )

        cfg = ConnectorConfig(
            source_id=uuid.uuid4(),
            url=self.surface_url,
            timeout=30,
            user_agent="PolarisBot/0.1 (provider discovery)",
        )
        connector = GenericPlaywrightConnector(cfg)
        try:
            await connector.connect()
            raw_links = await connector.discover()
        finally:
            await connector.close()

        discovered: list[DiscoveredOrganization] = []
        seen_domains: set[str] = set()
        for link in raw_links:
            if not self._allowed_url(link):
                continue
            domain = self._domain(link)
            if not domain or domain in seen_domains:
                continue
            seen_domains.add(domain)
            discovered.append(
                self._make_discovered(
                    name=domain,
                    org_type=self._infer_type(link),
                    url=link,
                    source=self.surface_url,
                    method="link_discovery",
                    confidence=0.5,
                    evidence={
                        "origin": "link_discovery",
                        "registered_domain": domain,
                        "tld_seen": next(
                            (s for s in self.allowed_tlds if domain.endswith(s)), ""
                        ),
                        "surface_type": self.organization_type,
                    },
                )
            )

        logger.info(
            "{}: produced {} organization(s) for {} ({} raw links, {} domains)",
            self.__class__.__name__,
            len(discovered),
            self.country.iso2,
            len(raw_links),
            len(seen_domains),
        )
        return discovered


class UniversityStrategy(LinkDiscoveryStrategy):
    organization_type = "University"


class GovernmentStrategy(LinkDiscoveryStrategy):
    organization_type = "Government"


class FoundationStrategy(LinkDiscoveryStrategy):
    organization_type = "Foundation"


class ScholarshipAgencyStrategy(LinkDiscoveryStrategy):
    organization_type = "Scholarship Agency"


class ResearchInstitutionStrategy(LinkDiscoveryStrategy):
    organization_type = "Research Institution"
