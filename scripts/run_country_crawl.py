"""Crawl every active source in a country for scholarship programmes.

This is the "find all scholarships that are possible for this country" runner:

    optional: provider discovery → source registration
    then:     every Active/Provisional source → page intent → programme pages
              → extraction → pending_review

Budgets are explicit and global (sources, pages per source, total pages,
runtime). The run is resumable in the ordinary sense: raw documents dedup by
checksum and scholarships by identity, so a second run does not create
duplicates. ``--skip-recent-days`` skips sources acquired recently.

Usage::

    python scripts/run_country_crawl.py JP --plan-only
    python scripts/run_country_crawl.py JP --discover --max-total-pages 200
    python scripts/run_country_crawl.py JP --max-sources 20 --max-pages-per-source 20

Live runs require a local database named ``*_test``/``*_scratch`` (or
``--allow-non-scratch``). The runner writes providers, sources, raw documents
and pending-review scholarships.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
from sqlalchemy import func


@dataclass
class CrawlTotals:
    sources_processed: int = 0
    sources_skipped: int = 0
    pages_fetched: int = 0
    candidates: int = 0
    extraction_succeeded: int = 0
    extraction_failed: int = 0
    persisted: int = 0
    duplicates: int = 0
    errors: int = 0


def print_plan(iso2: str) -> None:
    from services.exploration.config_loader import load_country_config

    config = load_country_config(iso2)
    print("\n" + "=" * 78)
    print(f"COUNTRY CRAWL PLAN — {config.iso2} ({config.country_name})")
    print("=" * 78)
    print("Database:      not opened (plan-only)")
    print(f"Official TLDs: {', '.join(config.soft_domain_signals) or '—'}")
    print(f"Seed portals ({len(config.seed_urls)}):")
    for url in config.seed_urls:
        print(f"  - {url}")
    print("Flow: provider discovery (optional) → all active sources → programme pages")
    print("=" * 78 + "\n")


def ensure_seed_sources(session, iso2: str) -> int:
    """Register the country config's official seed portals as sources.

    Provider discovery may yield nothing (a portal is not a list of providers,
    and some official sites live on .org). The config's ``seed_urls`` are
    already curated official starting points; without this they were only used
    by the exploration engine, never by the crawl runner. So a country with a
    valid config could still report zero sources.
    """
    from sqlalchemy import or_

    from database.models.country import Country
    from database.models.enums import ProviderType
    from database.models.provider import Provider
    from database.models.source_registry import SourceRegistry
    from services.exploration.config_loader import load_country_config
    from services.exploration.url_utils import domain_of, registered_domain
    from services.ingestion.ecosystem_strategies.link_discovery import (
        _ACADEMIC_SUFFIXES,
        _GOVERNMENT_SUFFIXES,
    )

    try:
        config = load_country_config(iso2)
    except FileNotFoundError:
        return 0

    country = session.query(Country).filter(Country.iso2 == iso2.upper()).first()
    if country is None:
        # A configured country that is missing from the reference table is a
        # setup gap, not a crawl result. Creating the row from the config keeps
        # "add a country" a data edit: the alternative was a run that reported
        # zero sources for a country that had eight configured portals.
        if not config.iso3:
            raise SystemExit(
                f"country {iso2} is not in the database and its config has no iso3"
            )
        country = Country(iso2=iso2.upper(), iso3=config.iso3, name=config.country_name)
        session.add(country)
        session.commit()
        logger.info("registered country {} ({}) from config", country.name, country.iso2)

    created = 0
    for url in config.seed_urls:
        domain = registered_domain(domain_of(url)) or domain_of(url)
        if not domain:
            continue
        # A seeded university page is a university, not a ministry. The seed
        # list is curated by hand, so the host suffix is the only signal we
        # have — and it is a reliable one for .edu.cn / .ac.jp style domains.
        if any(domain.endswith(suffix) for suffix in _ACADEMIC_SUFFIXES):
            provider_type = ProviderType.UNIVERSITY
        elif any(domain.endswith(suffix) for suffix in _GOVERNMENT_SUFFIXES):
            provider_type = ProviderType.GOVERNMENT
        else:
            provider_type = ProviderType.GOVERNMENT
        provider_code = domain.replace(".", "_").upper()
        if len(provider_code) > 32:
            import hashlib

            digest = hashlib.sha256(domain.encode()).hexdigest()[:6].upper()
            provider_code = f"{provider_code[:25]}_{digest}"
        provider = (
            session.query(Provider)
            .filter(or_(Provider.provider_code == provider_code, Provider.official_url == url))
            .first()
        )
        if provider is None:
            provider = Provider(
                provider_code=provider_code,
                provider_name=domain,
                provider_type=provider_type,
                country_id=country.country_id,
                official_url=f"https://{domain}",
                # A hand-written seed list is curated, not verified: nothing
                # in the pipeline has checked this host yet. Marking it
                # "verified" would let a config edit claim a trust level
                # that no verification step produced.
                verification_status="candidate",
            )
            session.add(provider)
            session.flush()

        # `crawl_entry_url` is unique too, and the radar (and the importers)
        # register sources by that column. Matching only `official_url` made the
        # seed step collide with an existing row and abort the whole run.
        source = (
            session.query(SourceRegistry)
            .filter(
                or_(SourceRegistry.official_url == url, SourceRegistry.crawl_entry_url == url)
            )
            .first()
        )
        if source is None:
            session.add(
                SourceRegistry(
                    source_name=f"{config.country_name} — {domain}",
                    country_id=country.country_id,
                    provider_id=provider.provider_id,
                    official_url=url,
                    crawl_entry_url=url,
                    crawl_method="Playwright",
                    connector_name="generic_playwright",
                    crawl_frequency="weekly",
                    priority=1,
                    status="Active",
                    robots_allowed=True,
                    requires_login=False,
                )
            )
            created += 1
    session.commit()
    return created


def _sources(session, iso2: str, max_sources: int, skip_recent_days: int, source_id=None):
    from datetime import datetime, timedelta, timezone

    from database.models.country import Country
    from database.models.source_registry import SourceRegistry
    from services.domain.source_trust import is_blocked_source_host

    country = session.query(Country).filter(Country.iso2 == iso2.upper()).first()
    if country is None:
        raise SystemExit(f"Country not found: {iso2}")

    query = session.query(SourceRegistry).filter(
        SourceRegistry.country_id == country.country_id,
        func.lower(SourceRegistry.status).in_(["active", "provisional"]),
    )
    if skip_recent_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=skip_recent_days)
        query = query.filter(
            (SourceRegistry.last_acquisition_at.is_(None))
            | (SourceRegistry.last_acquisition_at < cutoff)
        )
    if source_id is not None:
        query = query.filter(SourceRegistry.source_id == source_id)

    rows = query.order_by(SourceRegistry.priority, SourceRegistry.created_at).all()
    rows = [
        source
        for source in rows
        if not is_blocked_source_host(source.crawl_entry_url or source.official_url)
    ]
    return country, rows[:max_sources]


async def crawl_country(
    iso2: str,
    *,
    discover: bool,
    max_sources: int,
    source_id=None,
    max_pages_per_source: int,
    max_total_pages: int,
    max_runtime_minutes: int,
    skip_recent_days: int,
    allow_non_scratch: bool,
) -> CrawlTotals:
    from database.config import get_database_url
    from database.session import SessionLocal
    from services.exploration.acquisition_service import AcquisitionService
    from services.exploration.run_guard import assert_scratch_database

    assert_scratch_database(get_database_url(), allow_non_scratch=allow_non_scratch)

    session = SessionLocal()
    totals = CrawlTotals()
    deadline = time.monotonic() + max_runtime_minutes * 60
    try:
        if discover:
            from services.ingestion.country_coverage_orchestrator import (
                CountryCoverageOrchestrator,
            )

            logger.info("Bootstrapping providers/sources for {}...", iso2)
            bootstrap = CountryCoverageOrchestrator(iso2, session)
            await bootstrap.run_full_coverage(
                run_provider_discovery=True,
                run_scholarship_discovery=False,
                max_sources=max_sources,
            )
            logger.info(
                "Bootstrap: {} providers, {} sources",
                bootstrap.metrics.providers_discovered,
                bootstrap.metrics.sources_discovered,
            )

        seeded = ensure_seed_sources(session, iso2)
        if seeded:
            logger.info("Registered {} config seed source(s) for {}", seeded, iso2)

        _, sources = _sources(session, iso2, max_sources, skip_recent_days, source_id)
        logger.info("Crawling {} active source(s) for {}", len(sources), iso2)

        service = AcquisitionService(session)
        for source in sources:
            if totals.pages_fetched >= max_total_pages:
                logger.info("Total page budget reached ({}); stopping.", max_total_pages)
                break
            if time.monotonic() >= deadline:
                logger.info("Runtime budget reached; stopping.")
                break

            remaining = max_total_pages - totals.pages_fetched
            page_budget = min(max_pages_per_source, remaining)
            if page_budget <= 0:
                break

            logger.info(
                "Source {!r}: up to {} page(s)", source.source_name, page_budget
            )
            try:
                metrics = await service.acquire_from_source(
                    source,
                    max_pages=page_budget,
                    follow_indexes=True,
                    max_index_depth=2,
                    max_index_expansions=50,
                    max_children_per_index=10,
                )
            except Exception as exc:  # noqa: BLE001 — one source must not stop the country
                totals.errors += 1
                logger.error("Source {!r} failed: {}", source.source_name, exc)
                session.rollback()
                continue

            totals.sources_processed += 1
            totals.pages_fetched += metrics.pages_fetched
            totals.candidates += metrics.scholarship_urls_found
            totals.extraction_succeeded += metrics.extraction_succeeded
            totals.extraction_failed += metrics.extraction_failed
            totals.persisted += metrics.scholarships_persisted
            totals.duplicates += metrics.duplicates_collapsed
            totals.errors += len(metrics.errors)
            session.commit()

            print(
                f"  {source.source_name[:60]:60}  "
                f"pages={metrics.pages_fetched:2}  "
                f"extracted={metrics.extraction_succeeded:2}  "
                f"persisted={metrics.scholarships_persisted:2}"
            )

        return totals
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Exhaustive per-country scholarship crawl")
    parser.add_argument("iso2", help="Country ISO2 code, e.g. JP")
    parser.add_argument("--plan-only", action="store_true", help="Print plan and exit")
    parser.add_argument("--discover", action="store_true", help="Run provider/source discovery first")
    parser.add_argument("--max-sources", type=int, default=50)
    parser.add_argument("--max-pages-per-source", type=int, default=25)
    parser.add_argument("--max-total-pages", type=int, default=300)
    parser.add_argument("--max-runtime", type=int, default=30, help="Minutes")
    parser.add_argument("--skip-recent-days", type=int, default=0)
    parser.add_argument("--source-id", help="Only crawl this source UUID", default=None)
    parser.add_argument("--allow-non-scratch", action="store_true")
    args = parser.parse_args()

    if args.plan_only:
        print_plan(args.iso2.upper())
        return

    totals = asyncio.run(
        crawl_country(
            args.iso2.upper(),
            discover=args.discover,
            max_sources=args.max_sources,
            source_id=args.source_id,
            max_pages_per_source=args.max_pages_per_source,
            max_total_pages=args.max_total_pages,
            max_runtime_minutes=args.max_runtime,
            skip_recent_days=args.skip_recent_days,
            allow_non_scratch=args.allow_non_scratch,
        )
    )

    print("\n" + "=" * 78)
    print(f"COUNTRY CRAWL REPORT — {args.iso2.upper()}")
    print("=" * 78)
    print(f"Sources processed:     {totals.sources_processed}")
    print(f"Pages fetched:         {totals.pages_fetched}")
    print(f"Candidates:            {totals.candidates}")
    print(f"Extraction succeeded:  {totals.extraction_succeeded}")
    print(f"Extraction failed:     {totals.extraction_failed}")
    print(f"Scholarships persisted:{totals.persisted}")
    print(f"Duplicates collapsed:  {totals.duplicates}")
    print(f"Errors:                {totals.errors}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
