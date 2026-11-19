"""Publication quality gates.

M9 principle 1: *if information is unavailable, represent it explicitly as
unavailable.* This module is where that representation is decided.

The M8 pipeline collapsed four different situations into one:

    the page states no deadline           |
    the page states an open-ended policy  |
    we never fetched that field          ├─► None ─► deadline_state='unknown'
    two sources disagree                 |            → publishable anyway

A reader cannot tell those apart, and neither can a reviewer. This module
separates them into five states, and a scholarship may only be APPROVED
when the fields a user needs to make a decision are genuinely KNOWN.

State vocabulary (the five the M9 brief specifies, mapped to reality):

    KNOWN           a value was read from the source and is usable
    NOT_APPLICABLE  the field does not exist for this kind of opportunity
                    (e.g. a government award with no university tie)
    UNKNOWN         the source was read and was silent — this is real
                    information ("no deadline published") and is publishable
    MISSING         we expected the field and did not get it — a gap in our
                    own acquisition, NOT publishable
    CONFLICTING     sources disagree — unresolved, routes to review

The distinction that matters most is UNKNOWN vs MISSING. "This award
publishes no deadline" is a fact about the scholarship. "We failed to parse
the deadline" is a fact about Polaris, and a user acting on it could apply
late. Only the second blocks publication.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from services.domain.source_trust import aggregator_host
from services.ingestion.extraction_quality import (
    has_identity_tokens,
    name_genericities,
)


class FieldQuality:
    KNOWN = "KNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    # Alias used by callers that think in terms of "we did not get it".
    MISSING = "MISSING"
    CONFLICTING = "CONFLICTING"


# Fields a reader needs before deciding to apply. Derived from the API
# contract in api/schemas.py plus the matching criteria in
# docs/v0.1/filtering-engine-design-review.md §2.2 — not invented here.
#
# REQUIRED: without these the record cannot be acted on or scored.
#   identity  → the scholarship must be identifiable at all
#   provider  → matching and the source chain both key on it
#   country   → a scoring criterion worth 20 points
#   official source → the trust anchor; non-negotiable (M9 principle 2)
#   degree    → a scoring criterion worth 20 points
#
# OPTIONAL: real scholarships legitimately lack these, and the API already
# types them nullable. Requiring them would reject correct data.
#   funding_type, field_of_study, deadline, application_url, gpa, language,
#   research_experience, work_experience, benefits, timeline

REQUIRED_TO_PUBLISH = (
    "identity",
    "provider",
    "country",
    "official_source",
)

# Degree used to be required. It no longer is, and the reason is a trade the
# project has now made explicitly: a page that never states a level is common
# (a foundation's page describes who may apply, not what the award is for), and
# refusing those records kept real, verifiable awards out of the catalogue
# entirely — 36 of 43 pending records at one point. The level is still worth
# having, so it stays in the report as UNKNOWN with the reason stated, and the
# matching engine treats "not stated" as neutral rather than disqualifying.
#
# What this does NOT do is let a *wrong* level through: an extracted level is
# still validated against the vocabulary, and a conflicting one still blocks.
SOFT_FIELDS = ("degree",)

OPTIONAL_FIELDS = (
    "funding_type",
    "field_of_study",
    "deadline",
    "application_open",
    "application_cycle",
    "minimum_gpa",
    "ielts_required",
    "minimum_ielts",
    "toefl_required",
    "minimum_toefl",
    "research_experience",
    "work_experience",
    "publication",
    "benefits",
    "official_page_url",
)


# ---------------------------------------------------------------------------
# Placeholder source hosts
# ---------------------------------------------------------------------------
# A record's ``official_page_url`` is its trust anchor: it is the page a reader
# is told to verify against, and the thing the whole provenance chain hangs on.
# An approved record in the catalogue carried ``https://example.com/...`` as its
# official source. The existing gate could not catch it, because "the URL is
# non-empty" is all it asked — and ``example.com`` is non-empty.
#
# The rule is deliberately narrow. It matches names that are *reserved and can
# never resolve to a real provider* — RFC 2606 (``.test``, ``.example``,
# ``.invalid``, ``.localhost``, ``example.com/net/org``) and RFC 6761 plus the
# loopback addresses. It does not attempt to judge whether a domain is a
# *legitimate scholarship provider*, because that is a domain-reputation
# question this layer has no reliable input for: rejecting an unfamiliar host
# would reject real ministries and universities that Polaris has simply not seen
# before, which is a worse failure than the one being fixed.
PLACEHOLDER_SOURCE_HOSTS: frozenset[str] = frozenset(
    {"example.com", "example.net", "example.org", "localhost"}
)
PLACEHOLDER_TLDS: frozenset[str] = frozenset(
    {"example", "invalid", "localhost", "test"}
)
PLACEHOLDER_ADDRESSES: frozenset[str] = frozenset({"0.0.0.0", "::1"})


def placeholder_source_host(url: str | None) -> str | None:
    """The placeholder host in ``url``, or None when there is not one.

    Returns the offending host rather than a boolean so a refusal can name what
    it objected to. A bare host (``example.com``, no scheme) is accepted too: a
    reviewer typing one into a correction box gets the same verdict as a URL,
    instead of a pass because the string did not parse.
    """
    if not url or not str(url).strip():
        return None

    raw = str(url).strip()
    parsed = urlsplit(raw)
    if not parsed.netloc:
        # No scheme, so urlsplit read the whole thing as a path. Retry as a
        # scheme-relative URL so a bare "example.com/path" still resolves to a
        # host, and fall back to the first path segment for "example.com".
        parsed = urlsplit(f"//{raw}")

    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        return None

    bare = host[4:] if host.startswith("www.") else host
    if bare in PLACEHOLDER_SOURCE_HOSTS:
        return host
    if any(bare.endswith(f".{name}") for name in PLACEHOLDER_SOURCE_HOSTS):
        return host

    labels = bare.split(".")
    if labels and labels[-1] in PLACEHOLDER_TLDS:
        return host

    if bare in PLACEHOLDER_ADDRESSES or bare.startswith("127."):
        return host
    return None


def is_placeholder_source(url: str | None) -> bool:
    """Whether ``url`` names a placeholder host. See `PLACEHOLDER_SOURCE_HOSTS`."""
    return placeholder_source_host(url) is not None


def _json_safe(value: Any) -> Any:
    """Reduce a live field value to something JSON can hold, losslessly."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class FieldAssessment:
    """One field's quality, with the evidence behind the verdict."""

    field_name: str
    quality: str
    value: Any = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "field": self.field_name,
            "quality": self.quality,
            # Values come straight off the record, so they are dates and lists
            # as often as strings. A report is only useful if it survives
            # being stored as JSONB and returned over HTTP.
            "value": _json_safe(self.value),
            "detail": self.detail,
        }


@dataclass
class QualityReport:
    """The full gate result for one scholarship."""

    publishable: bool
    fields: dict[str, FieldAssessment] = field(default_factory=dict)
    blocking: list[str] = field(default_factory=list)
    conflicting: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "publishable": self.publishable,
            "blocking": self.blocking,
            "conflicting": self.conflicting,
            "fields": {name: a.to_dict() for name, a in self.fields.items()},
        }


def assess_scalar(
    name: str,
    value: Any,
    *,
    present: bool = True,
    conflicts: list | None = None,
) -> FieldAssessment:
    """Assess one scalar field.

    Args:
        present: whether acquisition actually reached this field. ``False``
            means MISSING (our gap). ``True`` with no value means UNKNOWN
            (the source was silent) — the distinction the whole module
            exists to preserve.
        conflicts: observed values from more than one source.
    """
    if conflicts and len({str(c) for c in conflicts}) > 1:
        return FieldAssessment(
            name, FieldQuality.CONFLICTING, None,
            f"sources disagree: {sorted(str(c) for c in conflicts)}",
        )
    if value is not None and str(value).strip() != "":
        return FieldAssessment(name, FieldQuality.KNOWN, value)
    if conflicts:
        # Sources agreed on "no value", which is a known absence.
        return FieldAssessment(name, FieldQuality.UNKNOWN, None, "all sources agree: not published")
    if not present:
        return FieldAssessment(name, FieldQuality.MISSING, None, "field was not read during acquisition")
    return FieldAssessment(name, FieldQuality.UNKNOWN, None, "source does not publish this field")


# The benefit flags Polaris stores. Named explicitly rather than read from the
# object's __dict__: an ORM instance's __dict__ contains SQLAlchemy internals
# such as _sa_instance_state, which is truthy, so a benefits row that grants
# nothing came back reporting an internal attribute as a granted benefit.
BENEFIT_FIELDS = (
    "tuition_fee",
    "monthly_allowance",
    "accommodation",
    "health_insurance",
    "travel_ticket",
    "research_grant",
)


def assess_benefits(benefits, present: bool = True) -> FieldAssessment:
    """Benefit flags are all-False when absent, which is ambiguous.

    An award that genuinely covers nothing is different from one whose
    benefits we failed to read. All-False with no acquisition evidence is
    reported as MISSING rather than silently meaning "covers nothing".
    """
    if not present or benefits is None:
        return FieldAssessment(
            "benefits", FieldQuality.MISSING, None, "benefits were not read during acquisition"
        )
    if hasattr(benefits, "items"):
        values = {name: benefits.get(name) for name in BENEFIT_FIELDS}
    else:
        values = {name: getattr(benefits, name, None) for name in BENEFIT_FIELDS}

    granted = sorted(name for name, value in values.items() if value)
    if granted:
        return FieldAssessment(
            "benefits", FieldQuality.KNOWN, granted, f"{len(granted)} benefit(s) recorded"
        )
    return FieldAssessment(
        "benefits", FieldQuality.UNKNOWN, [],
        "no benefits stated by the source; this is not the same as covering nothing",
    )


def assess_identity(name: str | None, *, name_verdict: dict | None = None) -> FieldAssessment:
    """Identity is special: without it nothing else matters.

    ``name_verdict`` carries the extractor's own reasoning so a reviewer can
    see *why* identity failed rather than only that it did.
    """
    if not name:
        reasons = (name_verdict or {}).get("reasons") or ["extractor produced no name"]
        return FieldAssessment("identity", FieldQuality.MISSING, None, "; ".join(reasons[:3]))

    # The same genericity rule the extractor applied. Re-judging the string
    # here with a looser test is how "Unknown Scholarship" came to be a
    # publishable name in the first place.
    genericities = name_genericities(name)
    if genericities:
        return FieldAssessment(
            "identity", FieldQuality.CONFLICTING, name, "; ".join(genericities[:3]),
        )

    has_identity, _ = has_identity_tokens(name)
    if not has_identity:
        return FieldAssessment(
            "identity", FieldQuality.CONFLICTING, name,
            "name carries no year, acronym or proper noun; verify against the source page",
        )
    return FieldAssessment("identity", FieldQuality.KNOWN, name)


def _conflict_map(conflicts: list | None) -> dict[str, list]:
    """Turn stored conflict records into {field: [values]}.

    A conflict on a field makes that field CONFLICTING regardless of any
    value stored on the row: the row holds one side of a disagreement, and
    presenting it as settled would hide the disagreement from the reviewer.
    """
    mapping: dict[str, list] = {}
    for entry in conflicts or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("field")
        if not name:
            continue
        values = [
            v.get("value") if isinstance(v, dict) else v
            for v in entry.get("values", [])
        ]
        # "deadline" and "application_deadline" name the same thing, so both
        # spellings are recorded and either resolves the conflict.
        canonical = "application_deadline" if name == "deadline" else name
        mapping[canonical] = values
        if canonical == "application_deadline":
            mapping.setdefault("deadline", values)
        else:
            mapping.setdefault("application_deadline", values)
    return mapping


def build_report(
    *,
    scholarship_name: str | None,
    name_verdict: dict | None,
    provider_name: str | None,
    country_name: str | None,
    official_page_url: str | None,
    degree: str | None,
    degree_levels: list[str] | None = None,
    funding_type: str | None = None,
    field_of_study: list | None = None,
    deadline_present: bool = True,
    application_deadline: Any = None,
    application_open: Any = None,
    application_cycle: Any = None,
    requirement=None,
    benefit=None,
    conflicts: list | None = None,
) -> QualityReport:
    """Run every gate and decide whether this record may be APPROVED.

    The decision is advisory by design: it is the *precondition* the review
    service checks before accepting an approval, never an approval itself.
    """
    cmap = _conflict_map(conflicts)
    fields: dict[str, FieldAssessment] = {}

    def scalar(name: str, value: Any, present: bool = True) -> FieldAssessment:
        # "deadline" is the gate's name for "application_deadline"; a stored
        # conflict may use either, so both spellings resolve to the same
        # assessment rather than one of them being silently ignored.
        conflict_values = cmap.get(name)
        if conflict_values is None and name == "deadline":
            conflict_values = cmap.get("application_deadline")
        return assess_scalar(name, value, present=present, conflicts=conflict_values)

    fields["identity"] = assess_identity(scholarship_name, name_verdict=name_verdict)
    fields["provider"] = scalar("provider", provider_name)
    fields["country"] = scalar("country", country_name)

    # Official source traceability is M9 principle 2 and is never optional.
    # A placeholder host is reported as MISSING, not as a lesser quality on a
    # present value: from a reader's point of view the record has no verifiable
    # source at all, which is exactly what MISSING means elsewhere in this
    # module. It is also the answer that blocks publication — `official_source`
    # is required, and it is deliberately absent from the overridable set in
    # ReviewService.approve.
    placeholder_host = placeholder_source_host(official_page_url)
    aggregator = aggregator_host(official_page_url)
    if aggregator:
        fields["official_source"] = FieldAssessment(
            "official_source", FieldQuality.MISSING, official_page_url,
            f"official source is a third-party aggregator ({aggregator}); "
            "the record must point at the provider's page",
        )
    elif placeholder_host:
        fields["official_source"] = FieldAssessment(
            "official_source", FieldQuality.MISSING, official_page_url,
            f"official source is a placeholder host ({placeholder_host}); "
            "a reserved test name cannot be a provider's page",
        )
    elif official_page_url:
        fields["official_source"] = FieldAssessment(
            "official_source", FieldQuality.KNOWN, official_page_url
        )
    else:
        fields["official_source"] = FieldAssessment(
            "official_source", FieldQuality.MISSING, None,
            "no official page URL: the record has no verifiable provenance chain",
        )

    # Degree is a 20-point scoring criterion and a soft gate: missing is
    # reported, not refused (see SOFT_FIELDS). A page that describes who may
    # apply without stating the award's level is ordinary, and refusing it kept
    # verifiable awards out of the catalogue.
    #
    # A record whose page stated a *set* of levels is not in that position: the
    # award's levels are known, there are just several of them.
    levels = [level for level in (degree_levels or []) if level]
    if degree:
        fields["degree"] = FieldAssessment("degree", FieldQuality.KNOWN, degree)
    elif levels:
        fields["degree"] = FieldAssessment(
            "degree", FieldQuality.KNOWN, ", ".join(levels)
        )
    else:
        fields["degree"] = FieldAssessment(
            "degree", FieldQuality.UNKNOWN, None,
            "level not stated on the page; published without a level value",
        )

    fields["funding_type"] = scalar("funding_type", funding_type)
    fields["field_of_study"] = scalar("field_of_study", field_of_study)
    fields["deadline"] = scalar("deadline", application_deadline, present=deadline_present)
    fields["application_deadline"] = fields["deadline"]
    fields["application_open"] = scalar("application_open", application_open)
    fields["application_cycle"] = scalar("application_cycle", application_cycle)
    if aggregator:
        fields["official_page_url"] = FieldAssessment(
            "official_page_url", FieldQuality.MISSING, official_page_url,
            f"third-party aggregator ({aggregator})",
        )
    elif placeholder_host:
        # Same value, same verdict as `official_source` above: reporting it as
        # KNOWN here would put a "this is fine" on the page a reviewer is
        # looking at while the gate refuses the record for that exact value.
        # Not blocking on its own — `official_page_url` is an optional field.
        fields["official_page_url"] = FieldAssessment(
            "official_page_url", FieldQuality.MISSING, official_page_url,
            f"placeholder host ({placeholder_host})",
        )
    elif official_page_url:
        fields["official_page_url"] = FieldAssessment(
            "official_page_url", FieldQuality.KNOWN, official_page_url
        )
    else:
        fields["official_page_url"] = FieldAssessment(
            "official_page_url", FieldQuality.UNKNOWN, None,
            "no separate official page recorded",
        )
    fields["application_url"] = (
        FieldAssessment("application_url", FieldQuality.KNOWN, official_page_url)
        if official_page_url
        else FieldAssessment("application_url", FieldQuality.UNKNOWN, None, "application page not separately recorded")
    )

    if requirement is not None:
        fields["minimum_gpa"] = scalar("minimum_gpa", requirement.minimum_gpa)
        fields["ielts_required"] = scalar("ielts_required", requirement.ielts_required)
        fields["minimum_ielts"] = scalar("minimum_ielts", requirement.minimum_ielts)
        fields["toefl_required"] = scalar("toefl_required", requirement.toefl_required)
        fields["minimum_toefl"] = scalar("minimum_toefl", requirement.minimum_toefl)
        fields["research_experience"] = scalar(
            "research_experience", requirement.research_experience
        )
        fields["work_experience"] = scalar("work_experience", requirement.work_experience)
        fields["publication"] = scalar("publication", requirement.publication)
    else:
        for name in (
            "minimum_gpa", "ielts_required", "minimum_ielts", "toefl_required",
            "minimum_toefl", "research_experience", "work_experience", "publication",
        ):
            fields[name] = FieldAssessment(
                name, FieldQuality.UNKNOWN, None, "no requirement record attached"
            )

    fields["benefits"] = assess_benefits(benefit)

    # Any conflict naming a field this report does not otherwise assess still
    # blocks, so a stored conflict is never silently dropped.
    for name in cmap:
        if name not in fields:
            fields[name] = FieldAssessment(
                name, FieldQuality.CONFLICTING, None,
                f"sources disagree: {sorted(str(v) for v in cmap[name])}",
            )

    conflicting = sorted(
        name for name, a in fields.items() if a.quality == FieldQuality.CONFLICTING
    )
    blocking = [
        name
        for name in REQUIRED_TO_PUBLISH
        if name in fields and fields[name].quality in (FieldQuality.MISSING, FieldQuality.UNKNOWN)
    ]
    blocking += [name for name in conflicting if name not in blocking]
    blocking = sorted(set(blocking))

    return QualityReport(
        publishable=not blocking,
        fields=fields,
        blocking=blocking,
        conflicting=conflicting,
    )
