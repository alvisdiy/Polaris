"""Country-independent article discovery from configured scholarship aggregators."""

from services.aggregator_discovery.adapters import (
    AggregatorCandidate,
    AggregatorSource,
    discover_configured_source,
    discover_html_candidates,
    discover_html_source,
    discover_rss_candidates,
    load_aggregator_sources,
)

__all__ = [
    "AggregatorCandidate",
    "AggregatorSource",
    "discover_configured_source",
    "discover_html_candidates",
    "discover_html_source",
    "discover_rss_candidates",
    "load_aggregator_sources",
]
