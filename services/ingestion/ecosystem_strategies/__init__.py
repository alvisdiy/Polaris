"""Exports for the ecosystem strategies package.

The package purposefully re-exports the abstract base and the helper model so that
importers can simply write:

```python
from services.ingestion.ecosystem_strategies import (
    DiscoveredOrganization,
    OrganizationDiscoveryStrategy,
)
```

When new concrete strategies are added they will be imported here via the
`__all__` list.
"""

from services.ingestion.ecosystem_strategies.base import (
    DiscoveredOrganization,
    OrganizationDiscoveryStrategy,
)

__all__ = [
    "DiscoveredOrganization",
    "OrganizationDiscoveryStrategy",
]
