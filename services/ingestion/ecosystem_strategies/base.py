"""Abstract base for organization discovery strategies."""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from database.models.country import Country


class DiscoveredOrganization(BaseModel):
    """A discovered scholarship-relevant organization."""

    model_config = ConfigDict(frozen=True)

    country_id: UUID
    name: str
    organization_type: str
    official_url: str
    discovery_source: str
    discovery_method: str
    confidence: float = 0.5
    evidence: dict[str, Any] = {}
    discovered_at: datetime = None

    def __init__(self, **data):
        if data.get('discovered_at') is None:
            data['discovered_at'] = datetime.now(timezone.utc)
        if data.get('evidence') is None:
            data['evidence'] = {}
        super().__init__(**data)


class OrganizationDiscoveryStrategy(abc.ABC):
    """Base class for all organization discovery strategies."""

    def __init__(self, country: "Country") -> None:
        self.country = country

    @abc.abstractmethod
    async def discover(self) -> list[DiscoveredOrganization]:
        """Discover organizations in this country."""
        pass

    def _make_discovered(
        self,
        name: str,
        org_type: str,
        url: str,
        source: str,
        method: str,
        confidence: float = 0.5,
        evidence: dict[str, Any] | None = None,
    ) -> DiscoveredOrganization:
        """Helper to construct a DiscoveredOrganization."""
        return DiscoveredOrganization(
            country_id=self.country.country_id,
            name=name,
            organization_type=org_type,
            official_url=url,
            discovery_source=source,
            discovery_method=method,
            confidence=confidence,
            evidence=evidence or {},
        )
