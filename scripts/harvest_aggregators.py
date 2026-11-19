"""Harvest official scholarship URLs from aggregator sites — as a radar only.

Aggregators such as fullyscholarships.com and opportunitiescircle.com publish a
page per scholarship and link to the provider's own page. That link is the useful
part: it is a *pointer* to an official source, found without spending crawl
budget on guessing search queries.

The boundary this module keeps, and the reason it is safe to use them at all:

* an aggregator is **never** a source and never a provider. Only the official URL
  it links to is registered, and only that URL is crawled;
* the aggregator's own text — its summary, its deadline, its funding claim — is
  not copied into a record. A record's facts still come from the provider's page,
  which is what `auto_review` and the quality gates check;
* social links, redirectors and other aggregators are dropped, so the radar does
  not chain from one aggregator to the next.

So an aggregator can tell Polaris *where* to look. It cannot tell Polaris what is
true.

    python scripts/harvest_aggregators.py --dry-run
    python scripts/harvest_aggregators.py --limit-articles 60 --register
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

from services.domain.source_trust import blocked_source_host  # noqa: E402
from services.exploration.url_utils import registered_domain  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Aggregators to read. `posts` are sitemaps of their article pages.
AGGREGATORS: dict[str, dict] = {
    "fullyscholarships.com": {
        "sitemaps": ["https://fullyscholarships.com/post-sitemap.xml"],
    },
    "opportunitiescircle.com": {
        "sitemaps": [
            "https://www.opportunitiescircle.com/post-sitemap.xml",
            "http://www.opportunitiescircle.com/post-sitemap2.xml",
            "http://www.opportunitiescircle.com/post-sitemap3.xml",
        ],
    },
}

# An article worth reading is about an award. Course, internship and job posts
# are the bulk of these sites and never link to a scholarship page.
_ARTICLE_SIGNAL = re.compile(
    r"scholarship|fellowship|grant|award|funding|bursary|studentship", re.IGNORECASE
)

# Outbound links that are never a provider page.
_NOT_OFFICIAL = re.compile(
    r"(?:facebook|twitter|x\.com|instagram|linkedin|youtube|tiktok|pinterest|"
    r"whatsapp|telegram|t\.me|bit\.ly|tinyurl|goo\.gl|google\.com/url|"
    r"opcircleacademy|googleusercontent|wp\.com|cloudflare)",
    re.IGNORECASE,
)

# ISO country from the host suffix, so a harvested source can be crawled by the
# country run it belongs to. Unknown suffix means "skip and report", not "assign
# to whichever country happens to be first".
_TLD_COUNTRY = {
    "my": "MY", "bn": "BN", "de": "DE", "uk": "GB", "au": "AU", "jp": "JP",
    "cn": "CN", "kr": "KR", "sg": "SG", "id": "ID", "fr": "FR", "nl": "NL",
    "ca": "CA", "nz": "NZ", "ie": "IE", "se": "SE", "ch": "CH", "it": "IT",
    "es": "ES", "at": "AT", "be": "BE", "dk": "DK", "no": "NO", "fi": "FI",
    "pl": "PL", "us": "US", "edu": "US",
    "hu": "HU", "cz": "CZ", "pt": "PT", "gr": "GR", "tr": "TR", "il": "IL",
    "ae": "AE", "sa": "SA", "qa": "QA", "in": "IN", "pk": "PK", "bd": "BD",
    "ng": "NG", "ke": "KE", "za": "ZA", "br": "BR", "mx": "MX", "cl": "CL",
    "ar": "AR", "ru": "RU", "ua": "UA", "ro": "RO", "bg": "BG", "hr": "HR",
    "si": "SI", "sk": "SK", "lt": "LT", "lv": "LV", "ee": "EE", "is": "IS",
    "lu": "LU", "mt": "MT", "cy": "CY", "tw": "TW", "hk": "HK", "th": "TH",
    "vn": "VN", "ph": "PH", "eg": "EG", "ma": "MA", "jo": "JO", "lb": "LB",
    "kz": "KZ", "by": "BY", "rs": "RS", "ge": "GE", "am": "AM", "az": "AZ",
}

# Hosts whose suffix names no country but whose owner is well known. The
# aggregator link is still only a pointer; this only decides which country run
# picks the source up.
_KNOWN_HOST_COUNTRY = {
    "chevening.org": "GB",
    "gatescambridge.org": "GB",
    "study-uk.britishcouncil.org": "GB",
    "cscuk.fcdo.gov.uk": "GB",
    "stipendiumhungaricum.hu": "HU",
    "studyinnl.org": "NL",
    "campusfrance.org": "FR",
    "fulbrightonline.org": "US",
    "foreign.fulbrightonline.org": "US",
    "daad.de": "DE",
}


def _country_for(host: str) -> str | None:
    for known, iso2 in _KNOWN_HOST_COUNTRY.items():
        if host == known or host.endswith("." + known):
            return iso2
    parts = host.split(".")
    if len(parts) >= 2:
        return _TLD_COUNTRY.get(parts[-1]) or _TLD_COUNTRY.get(parts[-2])
    return None


def _get(url: str, timeout: int = 25) -> str | None:
    try:
        response = httpx.get(
            url, headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True
        )
    except Exception:
        return None
    if response.status_code >= 400:
        return None
    return response.text


def _locs(xml: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml or "")


def _article_urls(sitemaps: list[str], limit: int) -> list[str]:
    urls: list[str] = []
    for sitemap in sitemaps:
        xml = _get(sitemap, timeout=30)
        urls.extend(_locs(xml or ""))
    # Newest last in a WordPress post sitemap: take from the end, and keep only
    # articles whose slug says they are about an award.
    interesting = [url for url in urls if _ARTICLE_SIGNAL.search(url.rsplit("/", 2)[-2])]
    return interesting[-limit:] if limit else interesting


def _official_links(article_url: str, html: str, aggregator_host: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href.startswith("http"):
            continue
        host = (urlparse(href).hostname or "").lower()
        if not host or host.endswith(aggregator_host) or aggregator_host.endswith(host):
            continue
        if _NOT_OFFICIAL.search(host) or blocked_source_host(href):
            continue
        if href not in found:
            found.append(href)
    return found


def harvest(limit_articles: int) -> list[dict]:
    hits: dict[str, dict] = {}
    for aggregator, config in AGGREGATORS.items():
        articles = _article_urls(config["sitemaps"], limit_articles)
        print(f"\n{aggregator}: {len(articles)} article(s) to read")
        for article in articles:
            html = _get(article)
            if not html:
                continue
            for link in _official_links(article, html, aggregator):
                host = (urlparse(link).hostname or "").lower()
                if link in hits:
                    continue
                hits[link] = {
                    "url": link,
                    "host": host,
                    "country": _country_for(host),
                    "found_on": aggregator,
                    "article": article,
                }
        print(f"  running total: {len(hits)} official URL(s)")
    return list(hits.values())


def register(hits: list[dict], *, batch_size: int) -> tuple[int, int]:
    from database.models.country import Country
    from database.models.enums import ProviderType
    from database.models.provider import Provider
    from database.models.source_registry import SourceRegistry
    from database.session import SessionLocal

    session = SessionLocal()
    created_sources = 0
    skipped = 0
    try:
        for hit in hits:
            iso2 = hit["country"]
            country = (
                session.query(Country).filter_by(iso2=iso2).first() if iso2 else None
            )
            if country is None:
                skipped += 1
                continue

            domain = registered_domain(hit["host"]) or hit["host"]
            provider = (
                session.query(Provider)
                .filter(
                    Provider.country_id == country.country_id,
                    Provider.official_url.ilike(f"%{domain}%"),
                )
                .first()
            )
            if provider is None:
                code = re.sub(r"[^A-Z0-9]", "_", domain.upper())[:28] + "_" + iso2
                provider = Provider(
                    provider_code=code,
                    provider_name=domain,
                    provider_type=ProviderType.UNIVERSITY,
                    country_id=country.country_id,
                    official_url=f"https://{domain}",
                    verification_status="candidate",
                )
                session.add(provider)
                session.flush()

            source = (
                session.query(SourceRegistry)
                .filter(SourceRegistry.crawl_entry_url == hit["url"])
                .first()
            )
            if source is None:
                session.add(
                    SourceRegistry(
                        source_id=uuid.uuid4(),
                        source_name=f"{domain} — harvested from {hit['found_on']}",
                        country_id=country.country_id,
                        provider_id=provider.provider_id,
                        official_url=hit["url"],
                        crawl_entry_url=hit["url"],
                        crawl_method="Playwright",
                        connector_name="generic_playwright",
                        crawl_frequency="weekly",
                        priority=2,
                        status="Active",
                        robots_allowed=True,
                        requires_login=False,
                        scholarship_page_urls=[
                            {"url": hit["url"], "origin": "aggregator_radar"}
                        ],
                    )
                )
                created_sources += 1
            else:
                urls = list(source.scholarship_page_urls or [])
                known = {(item.get("url") if isinstance(item, dict) else item) for item in urls}
                if hit["url"] not in known:
                    urls.append({"url": hit["url"], "origin": "aggregator_radar"})
                    source.scholarship_page_urls = urls
        session.commit()
        return created_sources, skipped
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-articles", type=int, default=40)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    hits = harvest(args.limit_articles)
    print(f"\n{len(hits)} official URL(s) found")
    for hit in hits[:30]:
        print(f"  [{hit['country'] or '??'}] {hit['url'][:100]}")

    if args.json:
        print(json.dumps(hits, indent=2))
    if args.register and hits:
        created, skipped = register(hits, batch_size=args.batch_size)
        print(f"registered {created} source(s); skipped {skipped} without a known country")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
