"""Factory for OrganizationDiscoveryStrategy implementations.

Each discovery source is represented by a ProviderDiscoveryConfig row which
specifies:
- `organization_type` (e.g. "University", "Government", ...)
- `discovery_strategy` (e.g. "link_discovery")

The factory maps those fields to a concrete `OrganizationDiscoveryStrategy`
subclass.  Currently only `UniversityStrategy` is provided, but the
architecture is extensible – adding a new strategy only requires adding it
to the `_REGISTRY` dict.
"""

from __future__ import annotations

from typing import Type

from services.ingestion.ecosystem_strategies.university_strategy import UniversityStrategy
from services.ingestion.ecosystem_strategies import OrganizationDiscoveryStrategy
from database.models.provider_discovery_config import ProviderDiscoveryConfig


class StrategyFactory:
    """Resolve a discovery strategy class from config.

    The factory is deliberately simple: it looks up a tuple of
    `(organization_type, discovery_strategy)` in the internal registry and
    returns the corresponding class.  If no entry exists, it raises a
    `KeyError` – the caller can then decide to log/skip the config.
    """

    _REGISTRY: dict[tuple[str, str], Type[OrganizationDiscoveryStrategy]] = {
        ("University", "link_discovery"): UniversityStrategy,
        # Future entries, e.g. ("Government", "api_discovery"): GovernmentStrategy,
    }

    @classmethod
    def get_strategy(
        cls,
        organization_type: str,
        country,
        surface_url: str,
        config: ProviderDiscoveryConfig,
    ) -> OrganizationDiscoveryStrategy:
        """Return an instantiated strategy.

        Args:
            organization_type: The type of organization this config discovers.
            country: The Country ORM object.
            surface_url: The discovery surface URL from the config.
            config: The full ProviderDiscoveryConfig row (allows strategies to
                access `max_urls_per_source` or custom settings).
        """
        key = (organization_type, config.discovery_strategy)
        try:
            StrategyCls = cls._REGISTRY[key]
        except KeyError as exc:
            raise KeyError(f"No discovery strategy registered for {key}") from exc
        return StrategyCls(country, surface_url)
