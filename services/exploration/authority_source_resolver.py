"""AuthoritySourceResolver — DISCOVERY PAGE ≠ AUTHORITY SOURCE.

Given a resolved provider, finds candidate official domains and official
scholarship pages via targeted search + soft authority signals. Never assumes
the first result is official, never treats a TLD as proof. If nothing
convincing is found, the opportunity is persisted as AUTHORITY_UNRESOLVED and
is retryable in later runs — never discarded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from loguru import logger

from services.exploration.search.base import SearchProvider, SearchQuery
from services.exploration.url_utils import domain_of, registered_domain

AUTHORITY_UNRESOLVED = "authority_unresolved"
AUTHORITY_CANDIDATES_FOUND = "authority_candidates_found"
AUTHORITY_RESOLVED = "authority_resolved"


@dataclass
class AuthorityCandidate:
    url: str
    score: float
    signals: dict = field(default_factory=dict)


@dataclass
class AuthorityResolution:
    status: str
    provider_domain: str | None = None
    official_page: AuthorityCandidate | None = None
    candidates: list[AuthorityCandidate] = field(default_factory=list)
    reasoning: str = ""


class AuthoritySourceResolver:
    def __init__(
        self,
        search_provider: SearchProvider,
        soft_domain_signals: list[str] | None = None,
        max_queries: int = 3,
    ) -> None:
        self.search_provider = search_provider
        self.soft_domain_signals = [s.lower() for s in (soft_domain_signals or [])]
        self.max_queries = max_queries

    async def resolve(
        self,
        org_name: str,
        provider_domain: str | None,
        scholarship_term: str = "scholarship",
        page_hints: list[str] | None = None,
    ) -> AuthorityResolution:
        """Find candidate official pages for the provider."""
        candidates: dict[str, AuthorityCandidate] = {}
        queries_built: list[str] = []

        if provider_domain:
            queries_built.append(f'"{org_name}" official site')
        queries_built.append(f'"{org_name}" {scholarship_term}')
        queries_built = queries_built[: self.max_queries]

        for q in queries_built:
            try:
                results = await self.search_provider.search(
                    SearchQuery(text=q, result_count=8)
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Authority search failed '{}': {}", q, exc)
                continue

            for r in results:
                score, signals = self._score_candidate(r.url, r.title, org_name, page_hints or [])
                if r.url not in candidates or score > candidates[r.url].score:
                    candidates[r.url] = AuthorityCandidate(url=r.url, score=score, signals=signals)

        if not candidates:
            return AuthorityResolution(
                status=AUTHORITY_UNRESOLVED,
                provider_domain=provider_domain,
                reasoning="no search results for authority queries",
            )

        ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
        top = ranked[0]
        status = AUTHORITY_RESOLVED if top.score >= 0.6 else AUTHORITY_CANDIDATES_FOUND
        return AuthorityResolution(
            status=status,
            provider_domain=registered_domain(domain_of(top.url)),
            official_page=top,
            candidates=ranked[:5],
            reasoning=f"top score {top.score:.2f}",
        )

    # ------------------------------------------------------------------
    # Soft authority scoring (TLD is a signal, never proof)
    # ------------------------------------------------------------------

    def _score_candidate(
        self, url: str, title: str, org_name: str, page_hints: list[str]
    ) -> tuple[float, dict]:
        signals: dict = {}
        score = 0.0
        host = domain_of(url)
        reg = registered_domain(host)
        path = urlparse(url).path.lower()

        # HTTPS (small positive)
        if url.lower().startswith("https://"):
            score += 0.05
            signals["https"] = True

        # Institutional domain patterns (soft)
        institutional = any(host.endswith(s) or reg.endswith(s) for s in self.soft_domain_signals)
        if institutional:
            score += 0.2
            signals["institutional_domain"] = True

        # Org name ↔ domain consistency
        org_tokens = {t for t in org_name.lower().replace("-", " ").split() if len(t) > 2}
        host_tokens = set(host.replace("-", ".").split("."))
        overlap = org_tokens & host_tokens
        if overlap:
            score += min(0.25, 0.12 * len(overlap))
            signals["org_in_domain"] = sorted(overlap)

        # Org name in title
        if org_name.lower() in (title or "").lower():
            score += 0.15
            signals["org_in_title"] = True

        # Scholarship-page shape
        if any(k in path for k in ("scholarship", "grant", "fellowship", "financial", "admission")):
            score += 0.15
            signals["scholarship_path"] = True

        # Aggregator/blog demotion (soft, not rejection)
        aggregator_markers = ("blog", "news", "list", "top-10", "top10", "aggregator")
        if any(m in path for m in aggregator_markers):
            score -= 0.1
            signals["likely_aggregator_path"] = True

        # Cross-hints from the discovery page (official links found there)
        for hint in page_hints:
            if hint and domain_of(hint) and registered_domain(domain_of(hint)) == reg:
                score += 0.1
                signals["referenced_from_discovery_page"] = True
                break

        return round(max(0.0, min(score, 0.95)), 2), signals
