"""Discover Chinese scholarship pages on official university domains.

China's national catalogue (campuschina.org, csc.edu.cn) sits behind a WAF that
answers HTTP 412 to every non-browser client, and its scholarship list is loaded
through a token-signed AJAX handler rather than plain HTML. Crawling it is not a
matter of a better user-agent.

What *is* reachable are the universities' own English sites: `en.sdu.edu.cn`,
`iso.sysu.edu.cn`, `yz.tsinghua.edu.cn` and dozens like them publish their
scholarship guides as ordinary pages. They are also the right sources under the
project's rule — the provider of a Chinese Government Scholarship place is the
university that hosts it, and the university page states the level, the funding
and the deadline.

So this importer does one thing: run `site:edu.cn` / `site:gov.cn` searches and
keep the URLs that are on an allowed Chinese domain and look like a scholarship
page. The hits become an importer work list on one source, and the normal crawl
fetches them — same shape as `import_studyinjapan.py`.

    python scripts/discover_china.py --queries 8            # print only
    python scripts/discover_china.py --queries 8 --register --batch-size 40
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.domain.source_trust import is_blocked_source_host  # noqa: E402
from services.exploration.search.base import SearchQuery  # noqa: E402
from services.exploration.search.ddgs import DDGSearchProvider  # noqa: E402

ALLOWED_SUFFIXES = (".edu.cn", ".ac.cn", ".gov.cn")

QUERY_TEMPLATES = (
    'site:edu.cn scholarship "international students" {year}',
    "site:edu.cn scholarship master program international",
    'site:edu.cn "Chinese Government Scholarship" application guide',
    "site:edu.cn scholarship doctoral international students",
    "site:edu.cn/en scholarship application guidelines",
    'site:gov.cn "Chinese Government Scholarship" application',
    "site:edu.cn Confucius Institute scholarship application",
    "site:edu.cn university scholarship undergraduate international",
)

# A page that is about a scholarship usually says so in its path or title.
SIGNAL_WORDS = (
    "scholarship",
    "scholarships",
    "funding",
    "financial-aid",
    "financial_aid",
    "fellowship",
)


def _allowed(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if is_blocked_source_host(url):
        return False
    return any(host.endswith(suffix) for suffix in ALLOWED_SUFFIXES)


def _looks_like_scholarship_page(url: str, title: str) -> bool:
    haystack = f"{url} {title}".lower()
    return any(word in haystack for word in SIGNAL_WORDS)


async def collect(queries: int, year: str, per_query: int) -> list[dict]:
    provider = DDGSearchProvider(max_results=per_query)
    seen: dict[str, dict] = {}
    for template in QUERY_TEMPLATES[:queries]:
        text = template.format(year=year)
        try:
            results = await provider.search(
                SearchQuery(text=text, country_iso2="CN", gl="cn", result_count=per_query)
            )
        except Exception as exc:  # a provider outage is not a crawl failure
            print(f"  query failed: {text!r} ({type(exc).__name__})")
            continue
        kept = 0
        for item in results:
            url = item.url.split("#", 1)[0]
            if not _allowed(url) or url in seen:
                continue
            if not _looks_like_scholarship_page(url, item.title or ""):
                continue
            seen[url] = {"url": url, "title": item.title or "", "query": text}
            kept += 1
        print(f"  {kept:>2} kept from {text!r}")
    return list(seen.values())


def register(hits: list[dict], batch_size: int, country_iso2: str) -> int:
    from database.models.country import Country
    from database.models.enums import ProviderType
    from database.models.provider import Provider
    from database.models.source_registry import SourceRegistry
    from database.session import SessionLocal

    session = SessionLocal()
    try:
        country = session.query(Country).filter_by(iso2=country_iso2.upper()).first()
        if country is None:
            raise SystemExit(f"unknown country {country_iso2}")
        provider = (
            session.query(Provider)
            .filter(Provider.provider_code == "CN_UNIVERSITIES")
            .first()
        )
        if provider is None:
            provider = Provider(
                provider_code="CN_UNIVERSITIES",
                provider_name="Chinese universities (scholarship pages)",
                provider_type=ProviderType.UNIVERSITY,
                country_id=country.country_id,
                official_url="https://www.moe.gov.cn/",
                verification_status="verified",
            )
            session.add(provider)
            session.flush()

        created = 0
        # `crawl_entry_url` is unique in the schema, and several hits are
        # already sources from the seed registry. So a hit whose URL is taken
        # is appended to that source's work list instead of becoming a
        # duplicate row, and only genuinely new URLs open a new batch.
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
            known = {
                (item.get("url") if isinstance(item, dict) else item) for item in urls
            }
            if hit["url"] not in known:
                urls.append({"url": hit["url"], "origin": "discover_china"})
                existing.scholarship_page_urls = urls

        for index in range(0, len(pending), batch_size):
            batch = pending[index : index + batch_size]
            name = f"China — university scholarship pages (batch {index // batch_size + 1})"
            source = (
                session.query(SourceRegistry)
                .filter(
                    SourceRegistry.country_id == country.country_id,
                    SourceRegistry.source_name == name,
                )
                .first()
            )
            payload = [
                {"url": hit["url"], "origin": "discover_china"} for hit in batch
            ]
            if source is not None:
                urls = list(source.scholarship_page_urls or [])
                known = {
                    (item.get("url") if isinstance(item, dict) else item)
                    for item in urls
                }
                source.scholarship_page_urls = urls + [
                    item for item in payload if item["url"] not in known
                ]
                continue
            source = SourceRegistry(
                source_id=uuid.uuid4(),
                source_name=name,
                country_id=country.country_id,
                provider_id=provider.provider_id,
                official_url=f"https://www.moe.gov.cn/#cn-batch-{index // batch_size + 1}",
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
            session.add(source)
            created += 1
        session.commit()
        print(f"registered {created} source batch(es), {len(hits)} URL(s)")
        return created
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=int, default=len(QUERY_TEMPLATES))
    parser.add_argument("--per-query", type=int, default=15)
    parser.add_argument("--year", default="2027")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--country", default="CN")
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--limit", type=int, default=300)
    args = parser.parse_args(argv)

    hits = asyncio.run(collect(args.queries, args.year, args.per_query))[: args.limit]
    print(f"\n{len(hits)} official-domain scholarship page(s)")
    for hit in hits[:40]:
        print(" -", hit["url"][:110])
    if args.register and hits:
        register(hits, args.batch_size, args.country)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
