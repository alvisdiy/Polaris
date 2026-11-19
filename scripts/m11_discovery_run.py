"""M11 — country-first discovery that follows index pages to detail pages.

POST-M10's expansion fed 36 curated URLs straight into extraction and got 0 new
records, because most of them were the *indexes* rather than the awards. This
script inverts that:

    country → official index surface → page intent → funding links
           → candidate detail pages → page intent again (URLs lie)
           → extraction → dedup → PENDING_REVIEW

Every stage is counted, so the funnel is measured rather than asserted. The
runner never approves anything; ``AcquisitionService._persist_with_dedup`` is
the only thing that writes a record and it routes every one to review.

    python scripts/m11_discovery_run.py --dry-run
    python scripts/m11_discovery_run.py --report p11_discovery_metrics.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import text  # noqa: E402

from database.models.source_registry import SourceRegistry  # noqa: E402
from database.session import SessionLocal  # noqa: E402
from services.exploration.page_intent import classify_page_intent  # noqa: E402
from services.exploration.url_utils import normalize_url  # noqa: E402
from services.ingestion.cleaner import clean  # noqa: E402
from services.ingestion.loader import LoadedDocument  # noqa: E402

USER_AGENT = "PolarisBot/0.4 (+M11 discovery research; contact: research)"

# Phase 1: five countries chosen for *different ecosystem structures*, not for
# volume. The point is to learn which shape of ecosystem yields detail pages.
TARGETS: list[tuple[str, str, str]] = [
    # (iso3, ecosystem shape, official index surface)
    ("GBR", "university-heavy", "https://www.lboro.ac.uk/study/undergraduate/fees-funding/scholarships/"),
    ("SGP", "institution-catalogue", "https://www.sp.edu.sg/admissions/scholarships-talent-programmes"),
    ("JPN", "government-programme", "https://www.studyinjapan.go.jp/en/planning/scholarship/types/"),
    ("DEU", "centralised-portal", "https://www.daad.de/en/studying-in-germany/scholarships/"),
    ("IDN", "provider-agency", "https://www.aminef.or.id/grants-for-indonesians/"),
    # V0.1 catalogue build. M11 measured the ecosystem shapes: university-heavy
    # and institution-catalogue yield detail pages, centralised portals do not.
    # These follow that evidence rather than adding volume blindly.
    ("GBR", "university-heavy", "https://www.lboro.ac.uk/study/postgraduate/fees-funding/scholarships/"),
    ("GBR", "university-heavy", "https://www.imperial.ac.uk/study/fees-funding/scholarships/"),
    ("GBR", "university-heavy", "https://www.ucl.ac.uk/prospective-students/graduate/financial-support/scholarships"),
    ("GBR", "university-heavy", "https://www.ed.ac.uk/student-funding/postgraduate-funding/scholarships"),
    ("SGP", "institution-catalogue", "https://www.nus.edu.sg/oam/scholarships"),
    ("SGP", "institution-catalogue", "https://www.ntu.edu.sg/admissions/undergraduate/scholarships"),
    ("AUS", "university-heavy", "https://www.monash.edu/study/fees-scholarships/scholarships"),
    ("CAN", "university-heavy", "https://www.ubc.ca/admissions/finances/scholarships"),
]

# Hosts that are never an official source for a scholarship, however many
# candidates they contribute. Social platforms and commercial aggregators are
# the two categories the frontier was filling up with.
_NON_OFFICIAL_HOSTS = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "linkedin.com", "tiktok.com", "pinterest.com", "reddit.com",
    "wikipedia.org", "wemakescholars.com", "scholarshipamerica.org",
    "indeed.com", "glassdoor.com", "reddit.com",
)


@dataclass
class Funnel:
    """One counter per transition. Nothing here is estimated."""

    surfaces: int = 0
    surface_fetched: int = 0
    surface_js_escalated: int = 0
    surface_intent: dict = field(default_factory=dict)
    surface_links_found: int = 0
    surface_links_not_official: int = 0
    links_not_official: int = 0
    links_irrelevant: int = 0
    links_already_known: int = 0
    links_duplicate_in_run: int = 0
    candidates: int = 0
    candidate_fetched: int = 0
    candidate_js_escalated: int = 0
    candidate_fetch_failed: int = 0
    candidate_intent: dict = field(default_factory=dict)
    detail_pages: int = 0
    extracted: int = 0
    nameless: int = 0
    schema_failed: int = 0
    invalid: int = 0
    duplicates: int = 0
    new_pending_review: int = 0
    failures: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    per_country: dict = field(default_factory=dict)

    def fail(self, category: str) -> None:
        self.failures[category] = self.failures.get(category, 0) + 1

    def bump(self, bucket: dict, key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1

    def as_dict(self) -> dict:
        return {
            "funnel": {
                "surfaces_attempted": self.surfaces,
                "surfaces_fetched": self.surface_fetched,
                "surfaces_needing_js": self.surface_js_escalated,
                "surface_page_intent": self.surface_intent,
                "links_found_on_surfaces": self.surface_links_found,
                "links_dropped_offsite": self.surface_links_not_official,
                "links_dropped_non_official_host": self.links_not_official,
                "links_dropped_not_funding_relevant": self.links_irrelevant,
                "links_dropped_already_known": self.links_already_known,
                "links_dropped_duplicate_in_run": self.links_duplicate_in_run,
                "detail_candidates": self.candidates,
                "candidates_fetched": self.candidate_fetched,
                "candidates_needing_js": self.candidate_js_escalated,
                "candidate_fetch_failed": self.candidate_fetch_failed,
                "candidate_page_intent": self.candidate_intent,
                "classified_detail_pages": self.detail_pages,
                "extraction_succeeded": self.extracted,
                "extraction_nameless": self.nameless,
                "schema_failures": self.schema_failed,
                "quality_failures": self.invalid,
                "duplicate_folds": self.duplicates,
                "new_pending_review": self.new_pending_review,
            },
            "failure_categories": self.failures,
            "per_country": self.per_country,
            "rows": self.rows,
        }


def _official_host(url: str) -> bool:
    from urllib.parse import urlparse

    host = urlparse(normalize_url(url)).netloc
    return bool(host) and not any(host.endswith("." + bad) or host == bad
                                   for bad in _NON_OFFICIAL_HOSTS)


def _funding_relevant(url: str, label: str) -> bool:
    """Does this link plausibly point at an opportunity?

    M11 §7. A scholarship index page's footer is full of links that have
    nothing to do with scholarships — imprint, privacy, contact, "back to
    top". Taking the first N same-site links turns the index into a list of
    legal pages, which is exactly the shape of the failure M10 hit.

    The href is checked first because many official sites encode the
    programme in the path; the anchor text is checked because plenty do not
    (`/edge-programme` is labelled "EDGE Programme").
    """
    from urllib.parse import urlparse

    from services.exploration.page_intent import FUNDING_TERMS
    from services.ingestion.connectors.generic_connector import (
        DEFAULT_DISCOVERY_KEYWORDS,
    )

    parsed = urlparse(url)
    url_signal = (parsed.path + "?" + parsed.query).casefold()
    label_signal = (label or "").casefold()
    keywords = [k.casefold() for k in (*DEFAULT_DISCOVERY_KEYWORDS, *FUNDING_TERMS)]
    return any(k in url_signal for k in keywords) or any(k in label_signal for k in keywords)


def _is_known(session, url: str) -> bool:
    """Has this URL already been fetched, or already became a scholarship?

    This is the pre-acquisition duplicate filter. It is deliberately a URL
    check, not an identity check: the identity machinery still runs after
    extraction, and nothing here can make a duplicate stop being a duplicate.
    """
    canonical = normalize_url(url)
    if not canonical:
        return True
    # Both spellings: normalize_url strips a trailing slash, and stored
    # source_url values keep it. Comparing only the normalised form misses
    # every URL the database happens to hold with a slash.
    a = canonical.rstrip("/")
    b = url.rstrip("/")
    row = session.execute(
        text(
            "SELECT 1 FROM raw_document WHERE rtrim(source_url, '/') IN (:a, :b) "
            "UNION SELECT 1 FROM scholarship "
            "WHERE rtrim(official_page_url, '/') IN (:a, :b) "
            "OR rtrim(application_url, '/') IN (:a, :b) LIMIT 1"
        ),
        {"a": a, "b": b},
    ).fetchone()
    return row is not None


def _ensure_source(session, url: str, iso3: str) -> SourceRegistry | None:
    from services.exploration.acquisition_policy import find_source

    existing = find_source(session, url)
    if existing is not None:
        return existing
    from database.models.country import Country

    country = session.query(Country).filter(Country.iso3 == iso3).first()
    try:
        source = SourceRegistry(
            source_name=url.split("/")[2],
            official_url=url,
            crawl_entry_url=url,
            crawl_method="http",
            connector_name="GenericHTTPConnector",
            crawl_frequency="manual",
            status="Active",
            verification_state="VERIFIED",
            country_id=country.country_id if country else None,
        )
        session.add(source)
        session.flush()
        return source
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        print(f"  SOURCE FAILED {url}: {exc}")
        return None


def _hrefs_with_labels(html: str, base_url: str) -> list[tuple[str, str]]:
    """(absolute_url, anchor_text) for every same-site link on the page."""
    from urllib.parse import urljoin, urlparse

    from bs4 import BeautifulSoup

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return []

    base_host = urlparse(base_url).netloc.lower()
    root = ".".join(base_host.split(".")[-2:]) if base_host else ""
    out: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        full = urljoin(base_url, href.split("#")[0])
        host = urlparse(full).netloc.lower()
        if not host:
            continue
        same_site = host == base_host or host.endswith("." + base_host) or (
            root and (host == root or host.endswith("." + root))
        )
        if not same_site:
            out.append((full, ""))  # kept, counted, and dropped by the caller
            continue
        label = " ".join(anchor.get_text(" ", strip=True).split())[:200]
        out.append((full, label))
    return out


async def _fetch(session, source_id, url: str, *, allow_js: bool = True):
    """HTTP first. Playwright only when the plain response is not enough.

    M11 §15: the browser is an escalation path, not the default. It is also
    the expensive one, and POST-M10 used it for every page.
    """
    from services.ingestion.connectors.base_connector import ConnectorConfig
    from services.ingestion.connectors.generic_connector import GenericHTTPConnector
    from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector

    config = ConnectorConfig(
        source_id=source_id, url=url, timeout=30, user_agent=USER_AGENT
    )
    http = GenericHTTPConnector(config)
    await http.connect()
    try:
        result = await http.fetch(url)
        cleaned = _clean_for(session, url, result.raw_content)
        if _sufficient(cleaned) or not allow_js:
            return result, cleaned, False
    except Exception as exc:  # noqa: BLE001
        print(f"  HTTP fetch failed {url}: {type(exc).__name__}")
        if not allow_js:
            raise
        result = None
        cleaned = None

    await http.close()
    pw = GenericPlaywrightConnector(config)
    await pw.connect()
    try:
        rendered = await pw.fetch(url)
        cleaned = _clean_for(session, url, rendered.raw_content)
        return rendered, cleaned, True
    finally:
        await pw.close()


def _clean_for(session, url: str, raw: str):
    source_id = session.execute(
        text("SELECT source_id FROM source_registry WHERE official_url = :u LIMIT 1"),
        {"u": url},
    ).scalar()
    return clean(
        LoadedDocument(
            document_id="",
            source_id=str(source_id or "00000000-0000-0000-0000-000000000000"),
            source_url=url,
            content_type="html",
            raw_content=raw,
        )
    )


def _sufficient(cleaned) -> bool:
    """Enough readable content to classify the page without a browser."""
    return (
        len(cleaned.clean_text or "") >= 800
        and bool(cleaned.page_title)
        and len(cleaned.headings) >= 1
    )


async def run(args) -> Funnel:
    from services.exploration.acquisition_service import AcquisitionService
    from services.ingestion.orchestrator import run_pipeline
    from services.ingestion.real_extractor import DeterministicLLMClient
    from services.ingestion.repositories.raw_document_mapper import RawDocumentMapper
    from services.ingestion.repositories.raw_document_repository import RawDocumentRepository

    funnel = Funnel()
    session = SessionLocal()
    raw_repo = RawDocumentRepository(session)
    raw_mapper = RawDocumentMapper()
    extractor = DeterministicLLMClient()
    acquisition = AcquisitionService(session)
    seen_this_run: set[str] = set()

    try:
        for iso3, shape, url in TARGETS:
            print(f"\n=== {iso3} ({shape}) {url}")
            funnel.surfaces += 1
            funnel.per_country.setdefault(iso3, {"shape": shape, "surface": url,
                                                 "candidates": 0, "detail": 0,
                                                 "new_pending_review": 0})
            source = _ensure_source(session, url, iso3)
            if source is None:
                funnel.fail("surface: source registration")
                continue

            # --- 1. the index surface itself ---
            try:
                surface_result, surface_clean, used_js = await _fetch(
                    session, source.source_id, url, allow_js=args.js
                )
            except Exception as exc:  # noqa: BLE001
                funnel.fail(f"surface fetch: {type(exc).__name__}")
                print(f"  SURFACE FAILED: {type(exc).__name__}")
                continue
            funnel.surface_fetched += 1
            funnel.surface_js_escalated += 1 if used_js else 0

            surface_intent = classify_page_intent(
                url=url,
                page_title=surface_clean.page_title,
                headings=surface_clean.headings,
                anchors=surface_clean.anchors,
                text=surface_clean.clean_text,
            )
            funnel.bump(funnel.surface_intent, surface_intent.intent)
            print(f"  surface intent: {surface_intent.intent} "
                  f"({surface_intent.confidence}) — {surface_intent.evidence[:1]}")
            print(f"  programme links on surface: {surface_intent.programme_links}")

            if not surface_intent.is_discovery_surface and not surface_intent.is_detail:
                # Nothing here and nothing to follow.
                continue

            # --- 2. follow the surface ---
            surface_html = surface_result.raw_content or ""
            links = _hrefs_with_labels(surface_html, url)
            funnel.surface_links_found += len(links)

            candidates: list[tuple[str, str]] = []
            for link, label in links:
                if not _official_host(link):
                    funnel.links_not_official += 1
                    continue
                if url.split("/")[2] not in link:
                    funnel.surface_links_not_official += 1
                    continue
                if not _funding_relevant(link, label):
                    funnel.links_irrelevant += 1
                    continue
                canonical = normalize_url(link)
                if canonical in seen_this_run:
                    funnel.links_duplicate_in_run += 1
                    continue
                if _is_known(session, canonical):
                    funnel.links_already_known += 1
                    continue
                seen_this_run.add(canonical)
                candidates.append((link, label))
                if len(candidates) >= args.max_candidates:
                    break

            funnel.candidates += len(candidates)
            funnel.per_country[iso3]["candidates"] += len(candidates)
            print(f"  detail candidates after dedup: {len(candidates)} "
                  f"(known {funnel.links_already_known}, offsite {funnel.surface_links_not_official})")

            # --- 3. acquire each candidate and judge it on its own content ---
            for link, label in candidates:
                try:
                    result, cleaned, used_js = await _fetch(
                        session, source.source_id, link, allow_js=args.js
                    )
                except Exception as exc:  # noqa: BLE001
                    funnel.candidate_fetch_failed += 1
                    funnel.fail(f"candidate fetch: {type(exc).__name__}")
                    continue
                funnel.candidate_fetched += 1
                funnel.candidate_js_escalated += 1 if used_js else 0

                intent = classify_page_intent(
                    url=link,
                    page_title=cleaned.page_title,
                    headings=cleaned.headings,
                    anchors=cleaned.anchors,
                    text=cleaned.clean_text,
                )
                funnel.bump(funnel.candidate_intent, intent.intent)
                if not intent.is_detail:
                    continue
                funnel.detail_pages += 1
                funnel.per_country[iso3]["detail"] += 1

                if args.dry_run:
                    print(f"  DETAIL {intent.confidence:.2f} {label[:50]!r} {link[:90]}")
                    funnel.rows.append({"url": link, "intent": intent.intent,
                                        "confidence": intent.confidence,
                                        "outcome": "dry-run"})
                    continue

                document = raw_mapper.to_orm(result)
                existing = raw_repo.get_by_source_and_checksum(
                    document.source_id, document.checksum
                )
                document = existing or raw_repo.save(document)

                pipeline = run_pipeline(str(document.document_id), session, extractor)
                if pipeline.raw_extraction.error:
                    funnel.schema_failed += 1
                    funnel.fail("schema: " + pipeline.raw_extraction.error[:40])
                    continue
                if not pipeline.is_valid:
                    funnel.invalid += 1
                    funnel.fail("validation")
                    continue

                extracted = pipeline.raw_extraction.scholarship
                if not extracted.scholarship_name:
                    funnel.nameless += 1
                    continue
                funnel.extracted += 1

                saved = acquisition._persist_with_dedup(
                    pipeline, str(document.document_id)
                )
                if saved is None:
                    funnel.duplicates += 1
                    outcome = "duplicate"
                else:
                    funnel.new_pending_review += 1
                    funnel.per_country[iso3]["new_pending_review"] += 1
                    outcome = "pending_review"
                funnel.rows.append({
                    "url": link, "intent": intent.intent,
                    "confidence": intent.confidence,
                    "name": extracted.scholarship_name, "outcome": outcome,
                })
                print(f"  DETAIL->{outcome}: {extracted.scholarship_name!r}")
                session.flush()

        if not args.dry_run:
            session.commit()
    finally:
        session.close()
    return funnel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--js", action="store_true", default=True)
    parser.add_argument("--max-candidates", type=int, default=12)
    parser.add_argument("--report", help="write the JSON metrics here")
    args = parser.parse_args()

    funnel = asyncio.run(run(args))
    print()
    print(json.dumps(funnel.as_dict(), indent=2, ensure_ascii=False))
    if args.report:
        Path(args.report).write_text(
            json.dumps(funnel.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
