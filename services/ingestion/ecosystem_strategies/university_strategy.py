"""University discovery strategy.

Historical entry point. The implementation now lives in
``link_discovery.py`` because government, foundation and agency surfaces use
the same mechanism with a different ``organization_type``. This module keeps
the import path stable for existing callers and tests.
"""

from __future__ import annotations

from services.ingestion.ecosystem_strategies.link_discovery import (
    UniversityStrategy,
)

__all__ = ["UniversityStrategy"]
