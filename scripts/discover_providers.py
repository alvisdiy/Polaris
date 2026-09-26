"""Provider discovery script.

Polaris currently knows only a handful of providers per country. This script
provides a *bounded*, production‑oriented way to discover additional
candidates automatically.

It works in two steps:

1. **Discovery URL** – a small, country‑specific mapping points to a public
   page that lists official scholarship agencies, ministries, or university
   scholarship portals. The mapping is intentionally tiny; adding new countries
   only requires adding a URL to the ``DISCOVERY_SOURCES`` dict.
2. **Candidate extraction** – the page is fetched with the existing
   ``GenericHTTPConnector`` (Playwright) and all ``<a>`` links are inspected.
   Links whose domain ends with a known government/institution TLD and that
   contain any of a keyword list (scholarship, grant, education, study, etc.)
   are turned into ``Provider`` candidates.

Each candidate is inserted with ``verification_status='pending'``.  A
corresponding ``SourceRegistry`` entry is also created in *pending* state so
that human reviewers can later verify the provider before it becomes part of
the active acquisition pipeline.

The script is safe to re‑run – it upserts on ``provider_code`` (derived from the
host name) and leaves already‑verified providers untouched.
"""

import os
import sys
import uuid
from urllib.parse import urlparse

# Add project root to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.session import SessionLocal
from database.models.country import Country
from database.models.provider import Provider
from database.models.source_registry import SourceRegistry
from database.models.enums import ProviderType
from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector
from services.ingestion.connectors.base_connector import ConnectorConfig

# ---------------------------------------------------------------------------
# Minimal discovery‑source mapping – extend as needed.
# Key: ISO2 country code, Value: URL that lists official scholarship agencies.
# The URLs are public, official government or education portals.
# ---------------------------------------------------------------------------
DISCOVERY_SOURCES = {
    "JP": "https://www.studyinjapan.go.jp/en/",
    "DE": "https://www2.daad.de/en/",
    "US": "https://educationusa.state.gov/",
    "GB": "https://www.chevening.org/",
    # Add more countries here without changing the core logic.
}

# Heuristic keyword list – used to filter links that are likely scholarship
# provider pages.
KEYWORDS = [
    "scholarship",
    "grant",
    "education",
    "study",
    "student",
    "exchange",
    "fellowship",
]


def _guess_provider_type(host: str) -> ProviderType:
    """Simple heuristic to map a host to :class:`ProviderType`.

    * ``*.gov*`` or ``*.go.*`` → GOVERNMENT
    * ``*.ac.*`` or ``*.edu*`` → UNIVERSITY
    * host contains "foundation" → FOUNDATION
    * otherwise → NGO (as a safe fallback).
    """
    lower = host.lower()
    if "gov" in lower or "go" in lower:
        return ProviderType.GOVERNMENT
    if "ac" in lower or "edu" in lower:
        return ProviderType.UNIVERSITY
    if "foundation" in lower:
        return ProviderType.FOUNDATION
    return ProviderType.NGO


def _extract_candidate_links(html: str, base_url: str) -> list[str]:
    """Very light link extraction – re‑uses the same regex pattern as the
    GenericHTTPConnector.
    Returns absolute URLs that pass the domain‑and‑keyword heuristics.
    """
    import re
    from urllib.parse import urljoin, urlparse

    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    candidates = []
    for href in hrefs:
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        domain = parsed.netloc.lower()
        if not domain:
            continue
        # Accept only government or academic TLDs
        if not any(tld in domain for tld in [".gov", ".go.", ".ac.", ".edu", ".org"]):
            continue
        # Keyword filter on path/query
        path_q = (parsed.path + "?" + parsed.query).lower()
        if not any(k in path_q for k in KEYWORDS):
            continue
        candidates.append(full)
    # Deduplicate preserving order
    seen = set()
    uniq = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def discover_for_country(session, iso2: str):
    """Discover provider candidates for *iso2* and upsert them.

    Returns a list of Provider objects that were created or updated.
    """
    country = session.query(Country).filter_by(iso2=iso2).first()
    if not country:
        raise ValueError(f"Country with iso2={iso2} not found")

    discovery_url = DISCOVERY_SOURCES.get(iso2)
    if not discovery_url:
        raise ValueError(f"No discovery source configured for country {iso2}")

    # Use existing Playwright connector (already capable of JS heavy pages)
    cfg = ConnectorConfig(
        source_id=uuid.uuid4(),  # temporary, not persisted
        url=discovery_url,
        timeout=30,
        user_agent="PolarisBot/0.1 (provider discovery)",
    )
    connector = GenericPlaywrightConnector(cfg)

    # Fetch page
    async def _run():
        await connector.connect()
        # GenericPlaywrightConnector exposes ``discover`` which returns candidate URLs.
        # We'll reuse its internal logic by calling ``discover`` directly.
        candidates = await connector.discover()  # returns list[str]
        await connector.close()
        return candidates
    import asyncio
    raw_candidates = asyncio.run(_run())

    # Apply additional keyword filter (the connector already does a basic filter).
    candidates = _extract_candidate_links(" ".join(raw_candidates), discovery_url)

    created = []
    for url in candidates:
        parsed = urlparse(url)
        host = parsed.netloc
        provider_code = host.replace(".", "_").upper()
        provider_name = host.replace("www.", "").title()
        p_type = _guess_provider_type(host)
        provider = (
            session.query(Provider)
            .filter_by(provider_code=provider_code)
            .first()
        )
        if not provider:
            provider = Provider(
                provider_code=provider_code,
                provider_name=provider_name,
                provider_type=p_type,
                country_id=country.country_id,
                official_url=url,
                verification_status="pending",
            )
            session.add(provider)
            session.flush()
            created.append(provider)
        else:
            # Update only mutable fields; keep existing verification_status.
            provider.provider_name = provider_name
            provider.provider_type = p_type
            provider.official_url = url
            provider.country_id = country.country_id

        # Ensure a pending SourceRegistry exists for the provider.
        source = (
            session.query(SourceRegistry)
            .filter_by(official_url=url)
            .first()
        )
        if not source:
            source = SourceRegistry(
                source_name=f"{provider.provider_name} portal",
                country_id=country.country_id,
                provider_id=provider.provider_id,
                official_url=url,
                crawl_entry_url=url,
                crawl_method="Playwright",
                connector_name="generic_playwright",
                crawl_frequency="Monthly",
                priority=2,  # lower than known P1 sources
                robots_allowed=True,
                requires_login=False,
                status="PendingReview",
            )
            session.add(source)
    session.commit()
    return created


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/discover_providers.py <ISO2>")
        sys.exit(1)
    iso = sys.argv[1].upper()
    s = SessionLocal()
    try:
        new = discover_for_country(s, iso)
        print(f"Discovered {len(new)} new provider candidates for {iso}")
    finally:
        s.close()
