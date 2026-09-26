"""ProviderResolver — cautious multi-signal identity resolution.

Provider identity ≠ URL and ≠ blind eTLD+1. Resolution combines registered
domain, normalized organization name, country, page identity (title/JSON-LD
Organization), and official references. Ambiguous evidence → NEEDS_REVIEW;
uncertain organizations are never auto-merged. Existing verified providers
are never downgraded.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models.enums import ProviderType
from database.models.provider import Provider
from services.exploration.candidate_analyzer import AnalyzedCandidate
from services.exploration.url_utils import domain_of, registered_domain

# Legal/organizational suffixes stripped when normalizing names
_NAME_SUFFIXES = (
    "inc", "llc", "ltd", "limited", "gmbh", "corp", "corporation",
    "foundation", "fondo", "fondation", "stiftung", "trust", "university",
    "université", "universität", "universitas", "college", "institute",
    "school", "agency", "organization", "association", "the", "of", "and",
)

# Page-chrome fragments that leak into candidate org names (footers, legal
# notices, CMS boilerplate). The first live SG run produced providers like
# "-2021 © Myanmar Study Abroad" and "Government of Singapore, last updated
# on 25 September 2026" — these are not organizations.
_NOISE_NAME_PATTERNS = (
    r"©",
    r"copyright",
    r"all rights reserved",
    r"last updated",
    r"last modified",
    r"privacy (?:policy|statement)",
    r"terms (?:of|&|and) (?:use|service)",
    r"cookie",
    r"^[-–—•·\s\d]+",  # leading dashes/bullets/years, e.g. "-2021 ..."
    r"back to (?:top|home)",
    r"skip to (?:main |content)",
)


def is_noise_org_name(name: str) -> bool:
    """True when a candidate org name is page chrome, not an organization."""
    lowered = (name or "").lower().strip()
    if not lowered:
        return True
    return any(re.search(p, lowered) for p in _NOISE_NAME_PATTERNS)


def normalize_org_name(name: str) -> str:
    name = (name or "").lower().strip()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    words = [w for w in name.split() if w and w not in _NAME_SUFFIXES]
    return " ".join(words)


def identity_key_for(registered_domain_value: str, normalized_name: str, country_id) -> str:
    return hashlib.sha256(
        f"{registered_domain_value}|{normalized_name}|{country_id}".encode("utf-8")
    ).hexdigest()


@dataclass
class ProviderResolution:
    provider: Provider
    created: bool
    confidence: float
    needs_review: bool
    reasoning: str


class ProviderResolver:
    def __init__(self, session: Session, country_id, soft_domain_signals: list[str] | None = None) -> None:
        self.session = session
        self.country_id = country_id
        self.soft_domain_signals = [s.lower() for s in (soft_domain_signals or [])]

    # ------------------------------------------------------------------
    # Identity extraction from a page
    # ------------------------------------------------------------------

    def extract_org_identity(self, analyzed: AnalyzedCandidate) -> tuple[str, float]:
        """Best-guess organization name from page features, with confidence.

        Candidates that are page chrome (copyright footers, legal notices,
        CMS boilerplate) are rejected before ranking; if nothing clean
        remains the low-confidence domain fallback is used instead.
        """
        candidates: list[tuple[str, float]] = []

        # JSON-LD Organization
        for item in analyzed.structured_data:
            if item.get("@type") in ("Organization", "CollegeOrUniversity", "EducationalOrganization", "GovernmentOrganization"):
                name = (item.get("name") or "").strip()
                if name and not is_noise_org_name(name):
                    candidates.append((name, 0.9))

        # og:site_name / copyright hints
        for hint in analyzed.org_hints[:3]:
            if 3 <= len(hint) <= 100 and not hint.lower().startswith(("http", "all rights")):
                if not is_noise_org_name(hint):
                    candidates.append((hint, 0.6))

        # Title-derived (first segment before separators often is the org)
        title = analyzed.title or ""
        for sep in (" | ", " – ", " — ", " :: "):
            if sep in title:
                part = title.split(sep)[0].strip()
                if 3 <= len(part) <= 100 and not is_noise_org_name(part):
                    candidates.append((part, 0.5))
                break

        if not candidates:
            domain = domain_of(analyzed.final_url or analyzed.url)
            if domain:
                base = domain.split(".")[0]
                # kebab/domain fallback, low confidence
                candidates.append((base.replace("-", " ").title(), 0.3))

        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return candidates[0]

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        org_name: str,
        url: str,
        page_title: str = "",
        evidence: dict | None = None,
    ) -> ProviderResolution:
        """Resolve an organization name + URL to a Provider row (cautious)."""
        domain = domain_of(url)
        reg_domain = registered_domain(domain)
        norm_name = normalize_org_name(org_name)

        if not norm_name:
            return self._create_needs_review(org_name or reg_domain or "unknown", url, "empty organization name", evidence)

        # Signal 1: exact identity_key match
        key = identity_key_for(reg_domain, norm_name, self.country_id)
        existing = self.session.query(Provider).filter(Provider.identity_key == key).first()
        if existing:
            self._append_evidence(existing, url, evidence)
            return ProviderResolution(existing, False, 0.9, False, "identity_key match")

        # Signal 2: same registered domain + country (domain-led identity)
        domain_match = (
            self.session.query(Provider)
            .filter(
                Provider.country_id == self.country_id,
                Provider.identity_key.isnot(None),
            )
            .all()
        )
        domain_match = [
            p for p in domain_match
            if p.identity_key and reg_domain and reg_domain in self._domain_of_provider(p)
        ]
        if len(domain_match) == 1:
            existing = domain_match[0]
            if not existing.is_verified() and self._names_compatible(norm_name, normalize_org_name(existing.provider_name)):
                # Strengthen identity: same domain AND compatible name
                existing.identity_key = key
                existing.identity_confidence = max(existing.identity_confidence or 0.0, 0.85)
                self._append_evidence(existing, url, evidence)
                self.session.flush()
                return ProviderResolution(existing, False, 0.85, False, "same registered domain + compatible name")
            if existing.is_verified():
                self._append_evidence(existing, url, evidence)
                return ProviderResolution(existing, False, 0.85, False, "same registered domain (verified provider)")

        if len(domain_match) > 1:
            # Same registered domain already produced several provider rows
            # (the live SG run built 3× admissions.smu.edu.sg from noisy page
            # titles). Consolidate into the earliest row instead of growing
            # another near-duplicate; dependents are re-pointed.
            primary, merged_count = self._merge_domain_duplicates(domain_match)
            self._append_evidence(primary, url, evidence)
            return ProviderResolution(
                primary, False, 0.8, False,
                f"same registered domain ({merged_count} near-duplicate rows merged)",
            )

        # Signal 3: same normalized name + country (name-led identity)
        name_matches = (
            self.session.query(Provider)
            .filter(Provider.country_id == self.country_id)
            .all()
        )
        name_matches = [
            p for p in name_matches
            if normalize_org_name(p.provider_name) == norm_name and not p.merged_into_provider_id
        ]
        if len(name_matches) == 1:
            existing = name_matches[0]
            self._append_evidence(existing, url, evidence)
            return ProviderResolution(existing, False, 0.7, False, "same normalized org name")

        if len(name_matches) > 1:
            # Ambiguous by name: do NOT auto-merge; create a needs_review candidate
            return self._create_needs_review(org_name, url, "ambiguous identity: multiple candidates", evidence)

        # No match: create new provider (discovered, identity recorded).
        # Initial evidence is stored as the first observation so that every
        # later rediscovery appends to a consistent provenance chain.
        first_observation = {
            "url": url,
            "at": datetime.now(timezone.utc).isoformat(),
            **(evidence or {}),
        }
        provider = Provider(
            provider_code=self._provider_code(reg_domain, norm_name),
            provider_name=org_name.strip()[:255],
            provider_type=self._infer_type(reg_domain),
            country_id=self.country_id,
            official_url=url[:2048],
            verification_status="discovered",
            discovery_source=url[:2048],
            discovery_method="internet_exploration",
            discovery_evidence={"observations": [first_observation]},
            discovered_at=datetime.now(timezone.utc),
            identity_key=key,
            identity_confidence=0.6,
        )
        try:
            self.session.add(provider)
            self.session.flush()
        except IntegrityError:
            # A concurrent-equivalent candidate in this run created the same
            # identity (or provider_code) first — e.g. two pages resolving to
            # the same normalized org name. Roll back the poisoned insert and
            # reuse the row that won (observed live on KR).
            self.session.rollback()
            existing = (
                self.session.query(Provider).filter(Provider.identity_key == key).first()
                or self.session.query(Provider)
                .filter(Provider.provider_code == provider.provider_code)
                .first()
            )
            if existing is None:
                raise
            self._append_evidence(existing, url, evidence)
            return ProviderResolution(existing, False, 0.8, False, "existing provider reused after code collision")
        logger.info("ProviderResolver: created provider '{}' ({})", org_name, reg_domain)
        return ProviderResolution(provider, True, 0.6, False, "new provider from discovery")

    def _merge_domain_duplicates(self, domain_match: list[Provider]) -> tuple[Provider, int]:
        """Consolidate near-duplicate providers sharing one registered domain.

        The earliest-discovered non-merged row becomes the primary; the rest
        are marked merged_into_provider_id and their scholarships/sources are
        re-pointed to it (rows are kept — FKs are RESTRICT and the merge trail
        stays auditable). Verified rows are preferred over discovered ones.
        """
        from database.models.scholarship import Scholarship
        from database.models.source_registry import SourceRegistry

        candidates = [p for p in domain_match if not p.merged_into_provider_id]
        if not candidates:
            candidates = list(domain_match)
        candidates.sort(
            key=lambda p: (
                0 if p.is_verified() else 1,
                p.discovered_at or datetime.max.replace(tzinfo=timezone.utc),
            )
        )
        primary = candidates[0]
        duplicates = [p for p in domain_match if p.provider_id != primary.provider_id]
        for dup in duplicates:
            if dup.merged_into_provider_id:
                continue
            dup.merged_into_provider_id = primary.provider_id
            self.session.query(Scholarship).filter(
                Scholarship.provider_id == dup.provider_id
            ).update({"provider_id": primary.provider_id})
            self.session.query(SourceRegistry).filter(
                SourceRegistry.provider_id == dup.provider_id
            ).update({"provider_id": primary.provider_id})
            logger.info(
                "ProviderResolver: merged duplicate '{}' into '{}' (same domain)",
                dup.provider_name, primary.provider_name,
            )
        self.session.flush()
        return primary, len(duplicates)

    def _create_needs_review(self, org_name: str, url: str, reason: str, evidence: dict | None) -> ProviderResolution:
        reg_domain = registered_domain(domain_of(url))
        norm = normalize_org_name(org_name)
        key = identity_key_for(reg_domain, norm, self.country_id) if norm else None
        provider = Provider(
            provider_code=self._provider_code(reg_domain, norm),
            provider_name=org_name.strip()[:255],
            provider_type=ProviderType.OTHER,
            country_id=self.country_id,
            official_url=url[:2048],
            verification_status="needs_review",
            discovery_source=url[:2048],
            discovery_method="internet_exploration",
            discovery_evidence={**(evidence or {}), "needs_review_reason": reason},
            discovered_at=datetime.now(timezone.utc),
            identity_key=key,
            identity_confidence=0.3,
        )
        code = provider.provider_code
        try:
            self.session.add(provider)
            self.session.flush()
        except IntegrityError:
            # Two ambiguous candidates resolving to the same identity (observed
            # live on KR as a provider_code UniqueViolation). Roll back the
            # poisoned insert and reuse the row that won instead of failing
            # the whole run.
            self.session.rollback()
            existing = None
            if code:
                existing = self.session.query(Provider).filter(Provider.provider_code == code).first()
            if existing is None and key:
                existing = self.session.query(Provider).filter(Provider.identity_key == key).first()
            if existing is None:
                raise
            self._append_evidence(existing, url, evidence)
            return ProviderResolution(existing, False, 0.3, True, reason)
        return ProviderResolution(provider, True, 0.3, True, reason)

    # ------------------------------------------------------------------

    @staticmethod
    def _domain_of_provider(provider: Provider) -> str:
        return registered_domain(domain_of(provider.official_url or ""))

    @staticmethod
    def _names_compatible(a: str, b: str) -> bool:
        if not a or not b:
            return False
        wa, wb = set(a.split()), set(b.split())
        if not wa or not wb:
            return False
        overlap = len(wa & wb) / max(len(wa), len(wb))
        return overlap >= 0.5

    @staticmethod
    def _provider_code(reg_domain: str, norm_name: str) -> str:
        base = (reg_domain or norm_name or "provider").replace(".", "_").upper()
        short = hashlib.sha256(f"{reg_domain}|{norm_name}".encode()).hexdigest()[:6].upper()
        code = f"{base[:24]}_{short}"
        return code[:32]

    @staticmethod
    def _infer_type(reg_domain: str) -> ProviderType:
        rd = reg_domain.lower()
        if any(rd.endswith(sfx) or f".{sfx}." in f".{rd}." for sfx in ("gov", "go", "gouv")):
            return ProviderType.GOVERNMENT
        if any(rd.endswith(sfx) or f".{sfx}." in f".{rd}." for sfx in ("edu", "ac")):
            return ProviderType.UNIVERSITY
        if "foundation" in rd or "fondation" in rd or "stiftung" in rd:
            return ProviderType.FOUNDATION
        if rd.endswith("org"):
            return ProviderType.NGO
        return ProviderType.OTHER

    @staticmethod
    def _append_evidence(provider: Provider, url: str, evidence: dict | None) -> None:
        stored = dict(provider.discovery_evidence or {})
        observations = list(stored.get("observations", []))
        observations.append({"url": url, "at": datetime.now(timezone.utc).isoformat(), **(evidence or {})})
        stored["observations"] = observations[-20:]
        provider.discovery_evidence = stored
        if not provider.discovery_source:
            provider.discovery_source = url[:2048]
        provider.discovered_at = provider.discovered_at or datetime.now(timezone.utc)
        provider.discovery_method = provider.discovery_method or "internet_exploration"
