"""VerificationEngine — the strict boundary.

Combines soft evidence into a confidence score (routing only) and an explicit
final state. TLD and keyword presence are never proof. States:
DISCOVERED / NEEDS_REVIEW / VERIFIED / REJECTED / DEPRECATED.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.domain.source_trust import aggregator_host
from services.exploration.url_utils import domain_of, registered_domain

STATE_DISCOVERED = "DISCOVERED"
STATE_NEEDS_REVIEW = "NEEDS_REVIEW"
STATE_VERIFIED = "VERIFIED"
STATE_REJECTED = "REJECTED"
STATE_DEPRECATED = "DEPRECATED"

# Generic official second-level domains. Every entry is ccTLD-bound, so an
# official-host match still anchors the source to a jurisdiction — the live
# SG run let finaid.org / uncf.org reach VERIFIED on content score alone;
# those are US aggregators, not Singaporean authorities.
_GENERIC_OFFICIAL_SUFFIXES = (
    ".gov", ".edu", ".ac", ".go", ".gouv", ".gov.uk", ".ac.uk",
    ".edu.au", ".gov.au", ".gov.sg", ".edu.sg", ".go.jp", ".ac.jp",
    ".gov.my", ".edu.my", ".ac.kr", ".go.kr", ".gov.cn", ".edu.cn",
    ".gov.in", ".ac.in", ".govt.nz", ".gc.ca", ".edu.hk", ".gov.hk",
)


@dataclass
class VerificationVerdict:
    state: str
    confidence: float
    signals: dict = field(default_factory=dict)
    reasoning: str = ""


class VerificationEngine:
    def __init__(
        self,
        soft_domain_signals: list[str] | None = None,
        auto_verify_threshold: float = 0.75,
        review_threshold: float = 0.45,
        auto_verify_enabled: bool = True,
    ) -> None:
        self.soft_domain_signals = [s.lower() for s in (soft_domain_signals or [])]
        self.auto_verify_threshold = auto_verify_threshold
        self.review_threshold = review_threshold
        self.auto_verify_enabled = auto_verify_enabled

    def verify_source(
        self,
        url: str,
        *,
        https_ok: bool = False,
        reachable: bool = False,
        org_identity_match: bool = False,
        provider_name: str = "",
        scholarship_content: bool = False,
        structured_data: bool = False,
        referenced_by_verified: bool = False,
        title: str = "",
    ) -> VerificationVerdict:
        """Verify a candidate source page. Strict: confidence must be earned."""
        aggregator = aggregator_host(url)
        if aggregator:
            # The verifier already refuses an aggregator *implicitly* by
            # requiring an institutional domain. Saying it explicitly keeps
            # the reason in the audit trail, and covers hosts that carry an
            # academic suffix without being a university (prospects.ac.uk).
            return VerificationVerdict(
                state=STATE_REJECTED,
                confidence=0.95,
                signals={"aggregator_host": aggregator},
                reasoning=(
                    f"{aggregator} is a third-party aggregator, "
                    "not an official scholarship source"
                ),
            )

        signals: dict = {}
        score = 0.0

        host = domain_of(url)
        reg = registered_domain(host)

        # TLS + reachability (mechanical prerequisites)
        if https_ok:
            score += 0.1
            signals["https"] = True
        if reachable:
            score += 0.1
            signals["reachable"] = True

        # Organization identity consistency (strong signal)
        if org_identity_match:
            score += 0.25
            signals["org_identity_match"] = True
            org_tokens = {t for t in provider_name.lower().split() if len(t) > 2}
            host_tokens = set(host.replace("-", ".").split("."))
            if org_tokens & host_tokens:
                score += 0.1
                signals["org_in_domain"] = True

        # Institutional domain pattern (SOFT — never proof)
        if any(host.endswith(s) or reg.endswith(s) for s in self.soft_domain_signals):
            score += 0.1
            signals["institutional_domain"] = True

        # Scholarship content presence (SOFT — never proof)
        if scholarship_content:
            score += 0.2
            signals["scholarship_content"] = True
        if structured_data:
            score += 0.05
            signals["structured_data"] = True

        # Reference from an already-verified source (community signal)
        if referenced_by_verified:
            score += 0.1
            signals["referenced_by_verified"] = True

        # Page self-identification
        if title and any(
            t in title.lower()
            for t in ("official", "university", "government", "ministry", "foundation")
        ):
            score += 0.05
            signals["self_identification"] = True

        confidence = round(min(score, 0.95), 2)

        # Official-host anchor: the registered domain (or host) carries a
        # governmental/academic suffix of some jurisdiction. Content alone is
        # never enough to auto-verify an aggregator domain.
        official_suffixes = tuple(self.soft_domain_signals) + _GENERIC_OFFICIAL_SUFFIXES
        is_official_host = any(
            reg.endswith(s) or host.endswith(s) for s in official_suffixes
        )
        signals["official_host"] = is_official_host

        # Explicit state decision — strict boundary
        if (
            confidence >= self.auto_verify_threshold
            and self.auto_verify_enabled
            and is_official_host
        ):
            state, reasoning = STATE_VERIFIED, f"confidence {confidence} ≥ auto-verify threshold (official host {reg})"
        elif confidence >= self.auto_verify_threshold and self.auto_verify_enabled:
            state, reasoning = STATE_NEEDS_REVIEW, (
                f"confidence {confidence} capped at review: host {reg} carries no "
                "official jurisdiction domain signal (aggregator guard)"
            )
        elif confidence >= self.review_threshold:
            state, reasoning = STATE_NEEDS_REVIEW, f"confidence {confidence} → human review"
        else:
            state, reasoning = STATE_DISCOVERED, f"confidence {confidence} below review threshold"

        return VerificationVerdict(state=state, confidence=confidence, signals=signals, reasoning=reasoning)
