"""Factory for organization-discovery strategies.

A `ProviderDiscoveryConfig` row says *what* to discover (organization type)
and *how* (discovery strategy). The factory turns that pair into a concrete
strategy. Adding a surface type is a config operation; adding a genuinely new
mechanism (sitemap, structured directory) is one registry entry.

Resolution order:

1. an explicit ``(organization_type, discovery_strategy)`` entry;
2. ``link_discovery`` for any known ProviderType, using the generic strategy
   with the configured organization type;
3. otherwise ``KeyError`` — the caller records it rather than guessing.
"""

from __future__ import annotations

from typing import Type

from database.models.enums import ProviderType
from database.models.provider_discovery_config import ProviderDiscoveryConfig
from services.ingestion.ecosystem_strategies import OrganizationDiscoveryStrategy
from services.ingestion.ecosystem_strategies.link_discovery import (
    FoundationStrategy,
    GovernmentStrategy,
    LinkDiscoveryStrategy,
    ResearchInstitutionStrategy,
    ScholarshipAgencyStrategy,
    UniversityStrategy,
)

_KNOWN_TYPES = {provider_type.value for provider_type in ProviderType}


class StrategyFactory:
    """Resolve a discovery strategy class from config."""

    _REGISTRY: dict[tuple[str, str], Type[OrganizationDiscoveryStrategy]] = {
        ("University", "link_discovery"): UniversityStrategy,
        ("Government", "link_discovery"): GovernmentStrategy,
        ("Foundation", "link_discovery"): FoundationStrategy,
        ("Scholarship Agency", "link_discovery"): ScholarshipAgencyStrategy,
        ("Research Institution", "link_discovery"): ResearchInstitutionStrategy,
    }

    @classmethod
    def get_strategy(
        cls,
        organization_type: str,
        country,
        surface_url: str,
        config: ProviderDiscoveryConfig,
    ) -> OrganizationDiscoveryStrategy:
        """Return an instantiated strategy, or raise KeyError with the pair."""
        key = (organization_type, config.discovery_strategy)
        strategy_cls = cls._REGISTRY.get(key)

        if strategy_cls is None:
            if config.discovery_strategy == "link_discovery" and organization_type in _KNOWN_TYPES:
                strategy_cls = LinkDiscoveryStrategy
            else:
                raise KeyError(
                    f"No discovery strategy registered for {key}. "
                    f"Known types: {sorted(_KNOWN_TYPES)}"
                )

        return strategy_cls(
            country,
            surface_url,
            organization_type=organization_type,
            allowed_tlds=list(config.allowed_tlds or []),
            keyword_filters=list(config.keyword_filters or []),
        )
