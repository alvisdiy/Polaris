"""Evidence-first ingestion of discovered aggregator articles.

All network access is injected. Production callers must provide a fetcher built
on ``GenericPlaywrightConnector``/``SafeFetch``; tests provide local responses.
Aggregator sources are never marked VERIFIED and never become providers.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models.country import Country
from database.models.provider import Provider
from database.models.raw_document import RawDocument
from database.models.source_registry import SourceRegistry, SourceVerificationState
from services.aggregator_discovery.adapters import AggregatorCandidate, AggregatorSource
from services.exploration.listing_guard import ListingVerdict, classify_listing_page
from services.exploration.page_intent import PageIntent, classify_page_intent
from services.exploration.url_utils import normalize_url, url_hash
from services.ingestion.cleaner import CleanedDocument, clean
from services.ingestion.extractor import ExtractedDocument, ExtractedScholarship
from services.ingestion.loader import LoadedDocument
from services.ingestion.orchestrator import _invoke_client
from services.ingestion.real_extractor import DeterministicLLMClient
from services.ingestion.validator import validate


@dataclass(frozen=True)
class FetchedPage:
    url: str
    body: str
    status_code: int = 200
    content_type: str = "html"


@dataclass(frozen=True)
class AggregatorIngestionResult:
    candidate_key: str
    state: str
    article_url: str
    article_document_id: str | None = None
    official_url: str | None = None
    official_document_id: str | None = None
    scholarship_id: str | None = None
    blockers: tuple[str, ...] = ()


def _page(value: Any, requested_url: str) -> FetchedPage:
    if isinstance(value, FetchedPage):
        return value
    if isinstance(value, str):
        return FetchedPage(url=requested_url, body=value)
    body = getattr(value, "raw_content", None)
    if body is None:
        raise TypeError("fetch_page must return FetchedPage, HTML text, or FetchResult")
    return FetchedPage(
        url=getattr(value, "final_url", None) or requested_url,
        body=body,
        status_code=getattr(value, "status_code", None) or 200,
        content_type=getattr(value, "content_type", "html"),
    )


def ensure_aggregator_source(session: Session, config: AggregatorSource) -> SourceRegistry:
    """Register the aggregator as an unverified acquisition surface."""
    entry = config.discovery_urls[0]
    row = (
        session.query(SourceRegistry)
        .filter(
            (SourceRegistry.official_url == config.base_url)
            | (SourceRegistry.crawl_entry_url == entry)
        )
        .with_for_update()
        .first()
    )
    if row is not None:
        provenance = row.discovered_via or {}
        if provenance.get("role") != "aggregator":
            raise ValueError(f"Configured aggregator URL is already registered as another source: {entry}")
        if row.official_url != config.base_url or row.crawl_entry_url != entry:
            raise ValueError(f"Aggregator configuration collides with a different registered source: {entry}")
        return row

    row = SourceRegistry(
        source_name=config.name,
        country_id=None,
        provider_id=None,
        official_url=config.base_url,
        crawl_entry_url=entry,
        crawl_method="aggregator_html",
        connector_name="GenericPlaywrightConnector",
        crawl_frequency="weekly",
        status="Active",
        verification_state=SourceVerificationState.NEEDS_REVIEW,
        discovered_via={"role": "aggregator", "config_id": config.id},
        page_type="aggregator",
        canonical_url=normalize_url(config.base_url),
        url_hash=url_hash(config.base_url),
        scholarship_page_urls=[],
    )
    session.add(row)
    session.flush()
    return row


def _record_candidate(source: SourceRegistry, candidate: AggregatorCandidate, **updates) -> dict:
    """Upsert one article's checkpoint in SourceRegistry's existing JSON field."""
    rows = list(source.scholarship_page_urls or [])
    key = hashlib.sha256(candidate.canonical_url.encode("utf-8")).hexdigest()
    current = next((item for item in rows if item.get("candidate_key") == key), None)
    if current is None:
        current = {
            "candidate_key": key,
            "source_id": candidate.source_id,
            "url": candidate.url,
            "canonical_url": candidate.canonical_url,
            "title": candidate.title,
            "discovered_from": candidate.discovered_from,
            "discovery_method": candidate.discovery_method,
            "discovered_page_intent": candidate.page_intent,
            "discovered_listing_verdict": candidate.listing_verdict,
            "state": "pending_review",
        }
        rows.append(current)
    current.update(updates)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    source.scholarship_page_urls = rows[-500:]
    return current


def _persist_raw_document(session: Session, source_id: UUID, page: FetchedPage) -> RawDocument:
    checksum = hashlib.sha256(page.body.encode("utf-8")).hexdigest()
    existing = (
        session.query(RawDocument)
        .filter(RawDocument.source_id == source_id, RawDocument.checksum == checksum)
        .first()
    )
    if existing is not None:
        return existing
    doc = RawDocument(
        source_id=source_id,
        source_url=page.url,
        content_type=page.content_type,
        raw_content=page.body,
        checksum=checksum,
        status_code=page.status_code,
        fetched_at=datetime.now(timezone.utc),
        processing_status="pending",
    )
    session.add(doc)
    session.flush()
    return doc


def _clean_page(document_id: str, source_id: UUID, page: FetchedPage) -> CleanedDocument:
    return clean(
        LoadedDocument(
            document_id=document_id,
            source_id=str(source_id),
            source_url=page.url,
            content_type="html",
            raw_content=page.body,
        )
    )


def _page_verdict(cleaned: CleanedDocument):
    intent = classify_page_intent(
        url=cleaned.source_url,
        page_title=cleaned.page_title,
        headings=cleaned.headings,
        anchors=cleaned.anchors,
        text=cleaned.clean_text,
    )
    listing = classify_listing_page(
        page_title=cleaned.page_title,
        headings=cleaned.headings,
        anchors=cleaned.anchors,
        text=cleaned.clean_text,
        intent=intent,
    )
    return intent, listing


def _country_code_from_title(session: Session, titles: list[str]) -> str | None:
    """Resolve one unambiguous country named in page titles/headings."""
    countries = session.query(Country).all()
    aliases = {
        "russia": "RU",
        "the netherlands": "NL",
        "netherlands": "NL",
        "turkey": "TR",
        "türkiye": "TR",
        "usa": "US",
        "united states": "US",
        "uk": "GB",
        "united kingdom": "GB",
    }
    for title in titles:
        normalized = (title or "").casefold()
        matches: set[str] = set()
        for alias, code in aliases.items():
            if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized):
                matches.add(code)
        for country in countries:
            if re.search(rf"(?<!\w){re.escape(country.name.casefold())}(?!\w)", normalized):
                matches.add(country.iso2.upper())
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1:
            return None
    return None


def _resolve_country(session: Session, article: CleanedDocument, official: CleanedDocument,
                     article_data: ExtractedScholarship, official_data: ExtractedScholarship) -> Country | None:
    # A named destination in an H1/title outranks a broad body-text heuristic.
    code = _country_code_from_title(
        session,
        [*official.headings[:2], official.page_title, *article.headings[:2], article.page_title],
    )
    if code is None:
        raw = official_data.country or article_data.country
        if raw and len(raw.strip()) == 2:
            code = raw.strip().upper()
        elif raw:
            row = session.query(Country).filter(func.lower(Country.name) == raw.strip().casefold()).first()
            if row:
                return row
    if code is None:
        return None
    return session.query(Country).filter(func.upper(Country.iso2) == code).first()


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    if hasattr(value, "model_dump"):
        return any(item is not None for item in value.model_dump().values())
    return True


def _opportunity_names_agree(article_name: str | None, official_name: str | None) -> bool:
    """Require recognizable identity overlap before treating a page as official evidence."""
    if not article_name or not official_name:
        return False
    generic = {
        "scholarship", "scholarships", "fellowship", "fellowships", "award", "awards",
        "program", "programme", "grant", "grants", "funded", "fully", "the", "for", "and", "of",
    }
    article_tokens = set(re.findall(r"[a-z0-9]+", article_name.casefold())) - generic
    official_tokens = set(re.findall(r"[a-z0-9]+", official_name.casefold())) - generic
    if not article_tokens or not official_tokens:
        return False
    overlap = len(article_tokens & official_tokens)
    return overlap >= 1 and overlap / len(article_tokens | official_tokens) >= 0.4


def _merge_verified_fields(article_data: ExtractedScholarship, official_data: ExtractedScholarship,
                           article_url: str, official_url: str, article_doc_id: str,
                           official_doc_id: str, country: Country) -> tuple[ExtractedScholarship, list[dict]]:
    fields = (
        "scholarship_name", "provider_name", "scholarship_type", "degree", "funding_type",
        "field_of_study", "application_url", "timeline", "eligibility", "benefits",
    )
    values: dict[str, Any] = {}
    provenance: dict[str, dict] = {}
    conflicts: list[dict] = []
    for name in fields:
        article_value = getattr(article_data, name)
        official_value = getattr(official_data, name)
        use_official = _nonempty(official_value)
        selected = official_value if use_official else article_value
        if name in {"timeline", "eligibility"}:
            merged = {}
            child_provenance = {}
            for child_name, article_child in article_value.model_dump().items():
                official_child = getattr(official_value, child_name)
                child_is_official = official_child is not None
                merged[child_name] = official_child if child_is_official else article_child
                child_provenance[child_name] = {
                    "source_url": official_url if child_is_official else article_url,
                    "document_id": official_doc_id if child_is_official else article_doc_id,
                    "origin": "official_source" if child_is_official else "aggregator_article",
                }
                if article_child is not None and official_child is not None and article_child != official_child:
                    conflict_field = "application_deadline" if child_name == "application_deadline" else child_name
                    conflicts.append({
                        "field": conflict_field,
                        "values": [
                            {"source_url": article_url, "value": article_child},
                            {"source_url": official_url, "value": official_child},
                        ],
                    })
            selected = type(article_value)(**merged)
            provenance[name] = child_provenance
        elif name == "benefits":
            article_values = article_value.model_dump()
            official_values = official_value.model_dump()
            merged = {}
            for child_name, article_child in article_values.items():
                official_child = official_values[child_name]
                merged[child_name] = official_child if official_child else article_child
                if article_child and official_child and article_child != official_child:
                    conflicts.append({
                        "field": child_name,
                        "values": [
                            {"source_url": article_url, "value": article_child},
                            {"source_url": official_url, "value": official_child},
                        ],
                    })
            selected = type(article_value)(**merged)
        elif _nonempty(article_value) and _nonempty(official_value) and article_value != official_value:
            field_name = "application_cycle" if name == "timeline" else name
            conflicts.append({
                "field": field_name,
                "values": [
                    {"source_url": article_url, "value": article_value},
                    {"source_url": official_url, "value": official_value},
                ],
            })
        values[name] = selected
        if name not in {"timeline", "eligibility"}:
            provenance[name] = {
                "source_url": official_url if use_official else article_url,
                "document_id": official_doc_id if use_official else article_doc_id,
                "origin": "official_source" if use_official else "aggregator_article",
            }

    # Country is stored under the canonical database name; a mismatch remains
    # explicit even when the official destination is selected.
    article_country = article_data.country
    official_country = official_data.country
    if article_country and official_country and article_country != official_country:
        conflicts.append({
            "field": "country",
            "values": [
                {"source_url": article_url, "value": article_country},
                {"source_url": official_url, "value": official_country},
            ],
        })
    values["country"] = country.name
    values["official_source"] = official_url
    meta = dict(article_data.extraction_meta or {})
    meta.update({
        "origin": "aggregator",
        "source_url": article_url,
        "document_id": article_doc_id,
        "method": "aggregator_article_verified_against_official_source",
        "official_document_id": official_doc_id,
        "official_verification_state": "VERIFIED",
        "field_evidence": provenance,
        "cross_source_conflicts": conflicts,
    })
    values["extraction_meta"] = meta
    return article_data.model_copy(update=values), conflicts


def _provider_for(session: Session, provider_name: str, official_url: str) -> Provider | None:
    matches = (
        session.query(Provider)
        .filter(func.lower(Provider.provider_name) == provider_name.strip().casefold())
        .all()
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None
    from services.exploration.provider_resolver import ProviderResolver

    resolution = ProviderResolver(session, country_id=None).resolve(
        provider_name,
        official_url,
        evidence={"discovery_method": "aggregator_article", "article_url": official_url},
    )
    return resolution.provider


class AggregatorIngestionService:
    def __init__(self, session: Session, fetch_page, *, article_limit: int = 10) -> None:
        self.session = session
        self.fetch_page = fetch_page
        self.article_limit = max(1, min(int(article_limit), 50))
        self.extractor = DeterministicLLMClient(default_country=None)

    async def process_candidate(
        self, config: AggregatorSource, candidate: AggregatorCandidate
    ) -> AggregatorIngestionResult:
        source = ensure_aggregator_source(self.session, config)
        key = hashlib.sha256(candidate.canonical_url.encode("utf-8")).hexdigest()
        observation = _record_candidate(source, candidate, state="processing")
        try:
            article_page = _page(await _maybe_await(self.fetch_page(candidate.url)), candidate.url)
        except Exception as exc:  # network failures remain visible in the candidate record
            observation.update(state="pending_review", blockers=[f"article_fetch_failed: {type(exc).__name__}"])
            self.session.flush()
            return AggregatorIngestionResult(key, "pending_review", candidate.url, blockers=("article_fetch_failed",))
        if article_page.content_type != "html" or article_page.status_code < 200 or article_page.status_code >= 300:
            observation.update(state="pending_review", blockers=["article_not_readable_html"])
            self.session.flush()
            return AggregatorIngestionResult(
                key, "pending_review", candidate.url, blockers=("article_not_readable_html",)
            )

        article_doc = _persist_raw_document(self.session, source.source_id, article_page)
        article_clean = _clean_page(str(article_doc.document_id), source.source_id, article_page)
        article_intent, article_listing = _page_verdict(article_clean)
        if not article_intent.is_detail or article_listing.verdict == ListingVerdict.HIGH_CONFIDENCE_LISTING:
            blocker = "article_not_confirmed_as_single_scholarship"
            observation.update(
                state="pending_review",
                article_document_id=str(article_doc.document_id),
                article_page_intent=article_intent.intent,
                listing_verdict=article_listing.verdict,
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(
                key, "pending_review", article_page.url, str(article_doc.document_id), blockers=(blocker,)
            )

        article_result = _invoke_client(self.extractor, article_clean)
        article_extracted = article_result.scholarship
        if article_extracted is None:
            blocker = "article_extraction_failed"
            observation.update(
                state="pending_review", article_document_id=str(article_doc.document_id), blockers=[blocker]
            )
            self.session.flush()
            return AggregatorIngestionResult(key, "pending_review", article_page.url,
                                             str(article_doc.document_id), blockers=(blocker,))

        article_validation = validate(article_result)
        if not article_validation.is_valid:
            blocker = "article_extraction_failed_validation"
            observation.update(
                state="pending_review",
                article_document_id=str(article_doc.document_id),
                validation_issues=[issue.model_dump() for issue in article_validation.issues],
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(
                key, "pending_review", article_page.url, str(article_doc.document_id), blockers=(blocker,)
            )

        official_url = article_extracted.official_source
        application_url = article_extracted.application_url
        if not official_url:
            blocker = "official_source_link_not_identified"
            observation.update(
                state="pending_review",
                article_document_id=str(article_doc.document_id),
                application_url_candidate=application_url,
                extracted_candidate=article_extracted.model_dump(mode="json"),
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(key, "pending_review", article_page.url,
                                             str(article_doc.document_id), blockers=(blocker,))

        try:
            official_page = _page(await _maybe_await(self.fetch_page(official_url)), official_url)
        except Exception as exc:
            blocker = "official_source_fetch_failed"
            observation.update(
                state="pending_review", article_document_id=str(article_doc.document_id),
                official_url_candidate=official_url, application_url_candidate=application_url,
                blockers=[f"{blocker}: {type(exc).__name__}"],
            )
            self.session.flush()
            return AggregatorIngestionResult(key, "pending_review", article_page.url,
                                             str(article_doc.document_id), official_url, blockers=(blocker,))
        if official_page.content_type != "html" or official_page.status_code < 200 or official_page.status_code >= 300:
            blocker = "official_source_not_readable_html"
            observation.update(
                state="pending_review", article_document_id=str(article_doc.document_id),
                official_url_candidate=official_url, application_url_candidate=application_url,
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(key, "pending_review", article_page.url,
                                             str(article_doc.document_id), official_url, blockers=(blocker,))

        official_doc = _persist_raw_document(self.session, source.source_id, official_page)
        official_clean = _clean_page(str(official_doc.document_id), source.source_id, official_page)
        official_intent, _ = _page_verdict(official_clean)
        official_extracted = _invoke_client(self.extractor, official_clean).scholarship
        provider_name = (
            (official_extracted.provider_name if official_extracted else None)
            or article_extracted.provider_name
        )
        from services.exploration.verification_engine import STATE_VERIFIED, VerificationEngine

        provider_tokens = {token.casefold() for token in (provider_name or "").split() if len(token) > 2}
        page_identity = " ".join([official_clean.page_title, *official_clean.headings[:3]]).casefold()
        org_match = bool(provider_tokens and any(token in page_identity for token in provider_tokens))
        verification = VerificationEngine().verify_source(
            official_page.url,
            https_ok=urlsplit(official_page.url).scheme == "https",
            reachable=True,
            org_identity_match=org_match,
            provider_name=provider_name or "",
            scholarship_content=official_intent.intent in {
                PageIntent.SCHOLARSHIP_DETAIL,
                PageIntent.SCHOLARSHIP_INDEX,
                PageIntent.SCHOLARSHIP_OVERVIEW,
            },
            title=official_clean.page_title,
        )
        if verification.state != STATE_VERIFIED:
            blocker = "official_source_requires_human_verification"
            observation.update(
                state="pending_review",
                article_document_id=str(article_doc.document_id),
                official_document_id=str(official_doc.document_id),
                official_url_candidate=official_page.url,
                application_url_candidate=application_url,
                official_verification={
                    "state": verification.state,
                    "confidence": verification.confidence,
                    "signals": verification.signals,
                    "reasoning": verification.reasoning,
                },
                extracted_candidate=article_extracted.model_dump(mode="json"),
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(
                key, "pending_review", article_page.url, str(article_doc.document_id),
                official_page.url, str(official_doc.document_id), blockers=(blocker,),
            )

        if official_extracted is None:
            blocker = "official_page_extraction_failed"
            observation.update(
                state="pending_review", article_document_id=str(article_doc.document_id),
                official_document_id=str(official_doc.document_id), official_url_candidate=official_page.url,
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(key, "pending_review", article_page.url,
                                             str(article_doc.document_id), official_page.url,
                                             str(official_doc.document_id), blockers=(blocker,))

        if not _opportunity_names_agree(
            article_extracted.scholarship_name, official_extracted.scholarship_name
        ):
            blocker = "official_opportunity_identity_unresolved"
            observation.update(
                state="pending_review", article_document_id=str(article_doc.document_id),
                official_document_id=str(official_doc.document_id), official_url_candidate=official_page.url,
                article_name=article_extracted.scholarship_name,
                official_name=official_extracted.scholarship_name,
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(
                key, "pending_review", article_page.url, str(article_doc.document_id),
                official_page.url, str(official_doc.document_id), blockers=(blocker,),
            )

        country = _resolve_country(
            self.session, article_clean, official_clean, article_extracted, official_extracted
        )
        provider_name = official_extracted.provider_name or article_extracted.provider_name
        if country is None or not provider_name or not article_extracted.scholarship_name:
            blockers = []
            if country is None:
                blockers.append("destination_country_unresolved")
            if not provider_name:
                blockers.append("provider_unresolved")
            if not article_extracted.scholarship_name:
                blockers.append("scholarship_name_unresolved")
            observation.update(
                state="pending_review", article_document_id=str(article_doc.document_id),
                official_document_id=str(official_doc.document_id), official_url_candidate=official_page.url,
                application_url_candidate=application_url,
                official_verification={"state": verification.state, "confidence": verification.confidence},
                extracted_candidate=article_extracted.model_dump(mode="json"), blockers=blockers,
            )
            self.session.flush()
            return AggregatorIngestionResult(
                key, "pending_review", article_page.url, str(article_doc.document_id),
                official_page.url, str(official_doc.document_id), blockers=tuple(blockers),
            )

        provider = _provider_for(self.session, provider_name, official_page.url)
        if provider is None:
            blocker = "provider_identity_ambiguous"
            observation.update(
                state="pending_review", article_document_id=str(article_doc.document_id),
                official_document_id=str(official_doc.document_id), official_url_candidate=official_page.url,
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(key, "pending_review", article_page.url,
                                             str(article_doc.document_id), official_page.url,
                                             str(official_doc.document_id), blockers=(blocker,))

        from services.scholarship.identity import assess_duplicate, scholarship_identity_key
        from services.scholarship.mapper import ScholarshipMapper

        merged, conflicts = _merge_verified_fields(
            article_extracted, official_extracted, article_page.url, official_page.url,
            str(article_doc.document_id), str(official_doc.document_id), country,
        )
        merged = merged.model_copy(update={
            "provider_name": provider.provider_name,
            "application_url": application_url or official_extracted.application_url,
            "official_source": official_page.url,
        })
        merged_meta = dict(merged.extraction_meta or {})
        field_evidence = dict(merged_meta.get("field_evidence") or {})
        selected_application_source = (
            official_page.url if application_url is None else article_page.url
        )
        selected_application_document = (
            str(official_doc.document_id) if application_url is None else str(article_doc.document_id)
        )
        if application_url:
            field_evidence["application_url"] = {
                "source_url": selected_application_source,
                "document_id": selected_application_document,
                "origin": "official_source" if selected_application_document == str(official_doc.document_id)
                else "aggregator_article",
            }
        merged_meta["field_evidence"] = field_evidence
        merged = merged.model_copy(update={"extraction_meta": merged_meta})
        merged_validation = validate(
            ExtractedDocument(
                document_id=str(article_doc.document_id),
                source_url=article_page.url,
                scholarship=merged,
            )
        )
        if not merged_validation.is_valid:
            blocker = "verified_extraction_failed_validation"
            observation.update(
                state="pending_review",
                article_document_id=str(article_doc.document_id),
                official_document_id=str(official_doc.document_id),
                official_url_candidate=official_page.url,
                extracted_candidate=merged.model_dump(mode="json"),
                validation_issues=[issue.model_dump() for issue in merged_validation.issues],
                blockers=[blocker],
            )
            self.session.flush()
            return AggregatorIngestionResult(
                key, "pending_review", article_page.url, str(article_doc.document_id),
                official_page.url, str(official_doc.document_id), blockers=(blocker,),
            )
        scholarship = ScholarshipMapper(self.session).to_orm(
            merged, str(source.source_id), document_url=official_page.url
        )
        scholarship.provenance_origin = "aggregator"
        scholarship.conflicts = conflicts or None
        scholarship.identity_key = scholarship_identity_key(
            scholarship.provider_id, scholarship.scholarship_name, scholarship.country_id
        )
        existing = assess_duplicate(self.session, canonical_key=scholarship.identity_key)
        if existing is not None:
            candidate_revision = None
            if existing.extraction_status == "approved":
                from services.exploration.acquisition_service import AcquisitionService
                from services.review import ReviewService

                observed = AcquisitionService(self.session, origin="aggregator")._observed_values(
                    scholarship, article_page.body
                )
                candidate_revision = ReviewService(self.session).propose_candidate(
                    existing,
                    observed=observed,
                    actor="aggregator_acquisition",
                    origin="aggregator",
                    source_url=article_page.url,
                    raw_document_id=str(article_doc.document_id),
                    reason="Aggregator re-discovery checked against a verified official page",
                )
                if candidate_revision is not None:
                    provenance = dict(candidate_revision.field_provenance or {})
                    provenance["evidence_document_ids"] = [
                        str(article_doc.document_id), str(official_doc.document_id)
                    ]
                    candidate_revision.field_provenance = provenance
            observation.update(
                state="duplicate_reviewed" if candidate_revision else "duplicate_existing",
                article_document_id=str(article_doc.document_id),
                official_document_id=str(official_doc.document_id),
                official_url=official_page.url,
                scholarship_id=str(existing.scholarship_id),
                candidate_revision_id=(str(candidate_revision.candidate_id) if candidate_revision else None),
                conflicts=conflicts,
                blockers=[],
            )
            self.session.commit()
            return AggregatorIngestionResult(
                key, observation["state"], article_page.url, str(article_doc.document_id),
                official_page.url, str(official_doc.document_id), str(existing.scholarship_id),
            )

        from database.models.scholarship_review_action import ReviewSource
        from services.scholarship.repository import ScholarshipRepository

        saved = ScholarshipRepository(self.session).save(scholarship)
        ReviewService(self.session).record_submission(
            saved,
            actor="aggregator_acquisition",
            source=ReviewSource.SYSTEM,
            evidence_url=article_page.url,
        )
        saved.quality_report = {
            **(saved.quality_report or {}),
            "official_source_verification": {
                "state": verification.state,
                "confidence": verification.confidence,
                "signals": verification.signals,
                "verified_url": official_page.url,
            },
        }
        observation.update(
            state="in_review",
            article_document_id=str(article_doc.document_id),
            official_document_id=str(official_doc.document_id),
            official_url=official_page.url,
            application_url=application_url or official_extracted.application_url,
            scholarship_id=str(saved.scholarship_id),
            official_verification={
                "state": verification.state,
                "confidence": verification.confidence,
                "signals": verification.signals,
            },
            conflicts=conflicts,
            blockers=[],
        )
        self.session.commit()
        return AggregatorIngestionResult(
            key, "in_review", article_page.url, str(article_doc.document_id),
            official_page.url, str(official_doc.document_id), str(saved.scholarship_id),
        )


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


async def run_configured_source(
    session: Session,
    config: AggregatorSource,
    *,
    article_limit: int = 10,
) -> list[AggregatorIngestionResult]:
    """Discover and process a bounded batch through the guarded connector.

    This function is the production integration point; callers choose the DB
    session, while every HTTP request still passes through URL safety, robots,
    redirect validation, and a one-second per-host delay. Nothing here approves
    or publishes records.
    """
    from services.ingestion.connectors.base_connector import ConnectorConfig
    from services.ingestion.connectors.generic_playwright import GenericPlaywrightConnector

    candidates = await discover_source_candidates(config)
    connector = GenericPlaywrightConnector(
        ConnectorConfig(
            source_id=uuid4(),
            url=config.discovery_urls[0],
            timeout=20,
            max_retries=1,
            user_agent="PolarisBot/0.1 (scholarship discovery)",
        )
    )
    last_request_at: float | None = None

    async def fetch_page(url: str) -> FetchedPage:
        nonlocal last_request_at
        loop = asyncio.get_running_loop()
        if last_request_at is not None:
            delay = 1.0 - (loop.time() - last_request_at)
            if delay > 0:
                await asyncio.sleep(delay)
        last_request_at = loop.time()
        result = await connector.fetch(url)
        return FetchedPage(
            url=result.final_url or url,
            body=result.raw_content,
            status_code=result.status_code or 200,
            content_type=result.content_type,
        )

    try:
        await connector.connect()
        service = AggregatorIngestionService(session, fetch_page, article_limit=article_limit)
        outcomes = []
        for candidate in candidates[: service.article_limit]:
            outcomes.append(await service.process_candidate(config, candidate))
            # Persist review checkpoints even when a fetch is blocked or facts
            # remain unresolved. This commit cannot change publication state.
            session.commit()
        return outcomes
    finally:
        await connector.close()


async def discover_source_candidates(config: AggregatorSource):
    """Adapter kept patchable for tests; performs the configured bounded read."""
    from services.aggregator_discovery.adapters import discover_configured_source

    return await discover_configured_source(config)
