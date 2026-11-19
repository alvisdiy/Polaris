"""Import the Study in Japan scholarship database as one source.

The site's search page paginates 25 detail records at a time. The pagination is
a JavaScript ``page(offset)`` that submits a GET form; direct HTTP requests with
the same parameters return page 1 because the server expects the session the
first page established. Playwright keeps that session, so the importer drives
the real page and collects every ``detail.php?mid=...`` link.

The source row stores those detail URLs in ``scholarship_page_urls``.
``AcquisitionService`` treats them as the work list, so a later
``run_country_crawl.py JP`` processes the database in bounded batches.

Usage::

    python scripts/import_studyinjapan.py --max-pages 4            # dry run
    python scripts/import_studyinjapan.py --max-pages 8 --register
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

SEARCH_URL = (
    "https://www.studyinjapan.go.jp/en/search-for-scholarships/"
    "tuition-reduction_search.php"
)
PAGE_SIZE = 25


async def enumerate_detail_urls(max_pages: int) -> list[str]:
    from playwright.async_api import async_playwright

    urls: list[str] = []
    seen: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (compatible; PolarisBot/0.2; scholarship research)"
        )
        page = await context.new_page()
        try:
            for index in range(max_pages):
                offset = index * PAGE_SIZE
                target = (
                    SEARCH_URL
                    if offset == 0
                    else f"{SEARCH_URL}?lang=en&offset={offset}&go=ofs"
                    f"&limit={PAGE_SIZE}&narabikae=2&school_name="
                )
                await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1200)
                hrefs = await page.eval_on_selector_all(
                    "a[href*='detail.php']", "els => els.map(e => e.href)"
                )
                new = [href for href in hrefs if href not in seen]
                seen.update(hrefs)
                urls.extend(new)
                logger.info(
                    "offset {}: {} links ({} new), total {}",
                    offset,
                    len(hrefs),
                    len(new),
                    len(urls),
                )
                if len(hrefs) < PAGE_SIZE or not new:
                    break
        finally:
            await context.close()
            await browser.close()

    return urls


def register_source(
    urls: list[str], country_iso2: str, *, batch_size: int = 50
) -> tuple[int, int]:
    from database.config import get_database_url
    from database.models.country import Country
    from database.models.enums import ProviderType
    from database.models.provider import Provider
    from database.models.source_registry import SourceRegistry
    from database.session import SessionLocal
    from services.exploration.run_guard import assert_scratch_database

    assert_scratch_database(get_database_url())

    session = SessionLocal()
    try:
        country = session.query(Country).filter(Country.iso2 == country_iso2.upper()).first()
        if country is None:
            raise SystemExit(f"Country not found: {country_iso2}")

        provider = (
            session.query(Provider)
            .filter(Provider.provider_code == "STUDYINJAPAN_GO_JP")
            .first()
        )
        if provider is None:
            provider = Provider(
                provider_code="STUDYINJAPAN_GO_JP",
                provider_name="Study in Japan (MEXT/JASSO)",
                provider_type=ProviderType.SCHOLARSHIP_AGENCY,
                country_id=country.country_id,
                official_url="https://www.studyinjapan.go.jp/en/",
                verification_status="verified",
            )
            session.add(provider)
            session.flush()

        source = (
            session.query(SourceRegistry)
            .filter(SourceRegistry.official_url == SEARCH_URL)
            .first()
        )
        if source is not None:
            # The unbounded row predates batching; retire it so a crawl does not
            # process the same first 50 URLs forever.
            source.status = "Retired"

        added = 0
        total = 0
        for index in range(0, len(urls), batch_size):
            batch = urls[index : index + batch_size]
            batch_number = index // batch_size + 1
            batch_url = f"{SEARCH_URL}?batch={batch_number}"
            batch_source = (
                session.query(SourceRegistry)
                .filter(SourceRegistry.official_url == batch_url)
                .first()
            )
            if batch_source is None:
                batch_source = SourceRegistry(
                    source_name=f"Study in Japan — database batch {batch_number}",
                    country_id=country.country_id,
                    provider_id=provider.provider_id,
                    official_url=batch_url,
                    crawl_entry_url=batch_url,
                    crawl_method="Playwright",
                    connector_name="generic_playwright",
                    crawl_frequency="weekly",
                    priority=0,
                    status="Active",
                    robots_allowed=True,
                    requires_login=False,
                )
                session.add(batch_source)

            existing = {
                item.get("url") if isinstance(item, dict) else item
                for item in (batch_source.scholarship_page_urls or [])
            }
            merged = [
                {"url": url, "origin": "studyinjapan_database"}
                for url in batch
                if url not in existing
            ]
            batch_source.scholarship_page_urls = (
                list(batch_source.scholarship_page_urls or []) + merged
            )[:batch_size]
            batch_source.status = "Active"
            added += len(merged)
            total += len(batch_source.scholarship_page_urls or [])

        session.commit()
        return added, total
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the Study in Japan database")
    parser.add_argument("--max-pages", type=int, default=8, help="Search pages of 25 records")
    parser.add_argument("--batch-size", type=int, default=50, help="URLs per source batch")
    parser.add_argument("--register", action="store_true", help="Write the source row")
    parser.add_argument("--country", default="JP")
    args = parser.parse_args()

    urls = asyncio.run(enumerate_detail_urls(args.max_pages))
    print(f"\nEnumerated {len(urls)} detail URL(s)")
    for url in urls[:5]:
        print(" -", url)

    if not args.register:
        print("\n(dry run: nothing written; pass --register to store the work list)")
        return

    added, total = register_source(urls, args.country, batch_size=args.batch_size)
    print(f"\nRegistered {added} new URL(s); batches now hold {total}.")


if __name__ == "__main__":
    main()
