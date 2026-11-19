"""Find scholarship pages on a country's official domains.

Country portals often publish scholarships as ordinary sub-pages rather than a
queryable database: a ministry's "scholarships" section, a university's funding
page, a foundation's call for applications. Those pages are the official source
the project wants, and search is how they are found.

This is the same shape as ``discover_china.py``, generalised: the country, its
allowed suffixes and its terminology all come from ``configs/countries/<ISO2>.json``,
so adding a country stays a data edit.

    python scripts/discover_official_pages.py MY --queries 6
    python scripts/discover_official_pages.py BN --queries 6 --register

Registers the hits as an importer work list, in batches, on one source per batch.
A URL that is already a source is appended to that source's work list instead of
creating a duplicate row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.domain.source_trust import is_blocked_source_host  # noqa: E402
from services.exploration.config_loader import load_country_config  # noqa: E402
from services.exploration.search.base import SearchQuery  # noqa: E402
from services.exploration.search.ddgs import DDGSearchProvider  # noqa: E402

SIGNAL_WORDS = (
    "scholarship",
    "scholarships",
    "biasiswa",
    "fellowship",
    "funding",
    "financial-aid",
    "financial_aid",
    "grant",
    "sponsorship",
)

# One template per query family. The country's own terminology fills the
# placeholder, so a Malay page is searched with Malay words.
TEMPLATES = (
    'site:{tld} {scholarship} "international students"',
    "site:{tld} {scholarship} application",
    "site:{tld} {scholarship} undergraduate postgraduate",
    "site:{tld} {scholarship} {education}",
    "site:{tld} {scholarship} {funding}",
    "site:{tld} {provider} {scholarship}",
)


def _allowed(url: str, suffixes: tuple[str, ...]) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not host or is_blocked_source_host(url):
        return False
    return any(host.endswith(suffix) for suffix in suffixes)


def _looks_like_scholarship_page(url: str, title: str) -> bool:
    haystack = f"{url} {title}".lower()
    return any(word in haystack for word in SIGNAL_WORDS)


async def collect(iso2: str, queries: int, per_query: int) -> list[dict]:
    config = load_country_config(iso2)
    suffixes = tuple(config.soft_domain_signals)
    if not suffixes:
        print(f"{iso2} has no soft_domain_signals; nothing to scope the search to")
        return []
    terminology = config.terminology or {}
    scholarship_terms = terminology.get("scholarship") or ["scholarship"]
    education_terms = terminology.get("education") or ["study"]
    funding_terms = terminology.get("funding") or ["funded"]
    provider_terms = terminology.get("provider") or ["university"]

    provider = DDGSearchProvider(max_results=per_query)
    seen: dict[str, dict] = {}
    plan: list[tuple[str, str]] = []
    for template in TEMPLATES:
        for tld in suffixes[:2]:
            plan.append((template, tld))

    for template, tld in plan[:queries]:
        text = (
            template.replace("{tld}", tld.lstrip("."))
            .replace("{scholarship}", scholarship_terms[0])
            .replace("{education}", education_terms[0])
            .replace("{funding}", funding_terms[0])
            .replace("{provider}", provider_terms[0])
        )
        try:
            results = await provider.search(
                SearchQuery(
                    text=text,
                    country_iso2=iso2,
                    gl=config.search_gl,
                    result_count=per_query,
                )
            )
        except Exception as exc:
            print(f"  query failed: {text!r} ({type(exc).__name__})")
            continue
        kept = 0
        for item in results:
            url = item.url.split("#", 1)[0]
            if url in seen or not _allowed(url, suffixes):
                continue
            if not _looks_like_scholarship_page(url, item.title or ""):
                continue
            seen[url] = {"url": url, "title": item.title or "", "query": text}
            kept += 1
        print(f"  {kept:>2} kept from {text!r}")
    return list(seen.values())


def register(iso2: str, hits: list[dict], batch_size: int) -> int:
    from database.models.country import Country
    from database.models.enums import ProviderType
    from database.models.provider import Provider
    from database.models.source_registry import SourceRegistry
    from database.session import SessionLocal

    config = load_country_config(iso2)
    session = SessionLocal()
    try:
        country = session.query(Country).filter_by(iso2=iso2.upper()).first()
        if country is None:
            if not config.iso3:
                raise SystemExit(f"country {iso2} missing and config has no iso3")
            country = Country(iso2=iso2.upper(), iso3=config.iso3, name=config.country_name)
            session.add(country)
            session.flush()

        code = f"{iso2.upper()}_UNIVERSITIES"
        provider = session.query(Provider).filter_by(provider_code=code).first()
        if provider is None:
            provider = Provider(
                provider_code=code,
                provider_name=f"{config.country_name} universities and ministries (funding pages)",
                provider_type=ProviderType.UNIVERSITY,
                country_id=country.country_id,
                official_url=config.seed_urls[0] if config.seed_urls else "",
                verification_status="candidate",
            )
            session.add(provider)
            session.flush()

        pending: list[dict] = []
        for hit in hits:
            existing = (
                session.query(SourceRegistry)
                .filter(SourceRegistry.crawl_entry_url == hit["url"])
                .first()
            )
            if existing is None:
                pending.append(hit)
                continue
            urls = list(existing.scholarship_page_urls or [])
            known = {(item.get("url") if isinstance(item, dict) else item) for item in urls}
            if hit["url"] not in known:
                urls.append({"url": hit["url"], "origin": "discover_official_pages"})
                existing.scholarship_page_urls = urls

        created = 0
        for index in range(0, len(pending), batch_size):
            batch = pending[index : index + batch_size]
            name = f"{config.country_name} — official funding pages (batch {index // batch_size + 1})"
            source = (
                session.query(SourceRegistry)
                .filter(
                    SourceRegistry.country_id == country.country_id,
                    SourceRegistry.source_name == name,
                )
                .first()
            )
            payload = [{"url": hit["url"], "origin": "discover_official_pages"} for hit in batch]
            if source is not None:
                urls = list(source.scholarship_page_urls or [])
                known = {(item.get("url") if isinstance(item, dict) else item) for item in urls}
                source.scholarship_page_urls = urls + [
                    item for item in payload if item["url"] not in known
                ]
                continue
            session.add(
                SourceRegistry(
                    source_id=uuid.uuid4(),
                    source_name=name,
                    country_id=country.country_id,
                    provider_id=provider.provider_id,
                    official_url=batch[0]["url"],
                    crawl_entry_url=batch[0]["url"],
                    crawl_method="Playwright",
                    connector_name="generic_playwright",
                    crawl_frequency="weekly",
                    priority=1,
                    status="Active",
                    robots_allowed=True,
                    requires_login=False,
                    scholarship_page_urls=payload,
                )
            )
            created += 1
        session.commit()
        print(f"registered {created} batch(es), {len(hits)} URL(s)")
        return created
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso2")
    parser.add_argument("--queries", type=int, default=8)
    parser.add_argument("--per-query", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    hits = asyncio.run(collect(args.iso2.upper(), args.queries, args.per_query))[: args.limit]
    print(f"\n{len(hits)} official-domain page(s)")
    for hit in hits[:30]:
        print(" -", hit["url"][:110])
    if args.json:
        print(json.dumps(hits, indent=2))
    if args.register and hits:
        register(args.iso2.upper(), hits, args.batch_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
