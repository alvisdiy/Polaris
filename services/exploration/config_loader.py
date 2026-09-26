"""Country exploration configuration loader.

Configuration is data: version-controlled JSON files under configs/countries/.
No configuration framework, no database table, no DSL — just validated
pydantic models with global defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "countries"


class Bounds(BaseModel):
    """Termination bounds for one exploration run."""

    max_depth: int = 3
    max_candidates: int = 2000
    max_pages: int = 300
    max_pages_per_domain: int = 15
    max_runtime_minutes: int = 45
    max_retries: int = 3


class RateLimits(BaseModel):
    per_domain_delay_ms: int = 1500
    fetch_timeout_seconds: int = 20
    search_timeout_seconds: int = 15


class Routing(BaseModel):
    """Classifier routing thresholds (confidence-aware, NOT hard gates)."""

    high_confidence: float = 0.75     # >= → normal opportunity pipeline
    medium_confidence: float = 0.45   # >= → lower-priority pipeline / review
    review_unknown: bool = True       # UNKNOWN retained (deferred), never discarded


class CountryExplorationConfig(BaseModel):
    """Everything the engine needs to explore one country."""

    iso2: str
    country_name: str
    country_local: str                      # native name for localized queries
    languages: list[str] = Field(default_factory=lambda: ["en"])
    search_locale: str = "en"
    search_gl: str = ""                     # geolocation param (e.g. "jp")
    terminology: dict[str, list[str]] = Field(default_factory=dict)
    query_families: list[str] = Field(
        default_factory=lambda: ["opportunity", "provider", "official_source", "localized"]
    )
    max_queries_per_run: int = 12
    seed_urls: list[str] = Field(default_factory=list)
    soft_domain_signals: list[str] = Field(default_factory=list)
    bounds: Bounds = Field(default_factory=Bounds)
    rate_limits: RateLimits = Field(default_factory=RateLimits)
    routing: Routing = Field(default_factory=Routing)


def load_country_config(iso2: str) -> CountryExplorationConfig:
    """Load and validate the country exploration config for an ISO2 code.

    Raises FileNotFoundError if no config file exists for the country.
    """
    path = CONFIG_DIR / f"{iso2.lower()}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No exploration config for country '{iso2}'. Expected: {path}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return CountryExplorationConfig.model_validate(data)


def available_countries() -> list[str]:
    """ISO2 codes (lowercase) of all configured countries."""
    if not CONFIG_DIR.exists():
        return []
    return sorted(p.stem for p in CONFIG_DIR.glob("*.json"))
