"""Deterministic review: decide what a machine can decide, and nothing more.

The review queue was the last step that needed a person (or a model) for every
record. Most of those records are not judgement calls:

* one passed every publication gate — there is nothing to decide;
* one is an aggregator page, a duplicate, an office homepage or a generic fee
  policy — no reading of it will make it publishable;
* the rest are genuinely ambiguous, and those are the ones a person should see.

This module draws that line with rules, so a nightly run can publish what is
already correct and *refuse* what is already impossible without spending a
token or waiting for a human. It never overrides a gate: an approval here means
"the gates passed", not "I think this is fine".

What it deliberately does not do: approve anything with a missing required
field, a name the extractor itself rejected, a provider that is still a domain,
or a page that says the round is closed. Those stay in `pending_review` with a
machine-written reason, which is a much smaller queue than "everything".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.ingestion.extraction_quality import name_genericities

APPROVE = "approve"
REJECT = "reject"
HOLD = "hold"

# A provider whose "name" is still a hostname is an artefact of discovery, not an
# organisation. Publishing under it puts "sysu.edu.cn" where a student expects
# "Sun Yat-sen University".
_DOMAINISH = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$", re.IGNORECASE)

# Batch labels created by importers. They are honest about provenance and useless
# as a provider name.
_GENERIC_PROVIDER = re.compile(
    r"^(?:chinese universities|.*university scholarship pages|.*universities \(.*\))$",
    re.IGNORECASE,
)

# Names that describe administration rather than an award a student applies to.
# These are the exact shapes that reached the queue as "complete" records:
# a grants service's own pages, a professional-licence scheme, and a grant
# programme for institutions.
_NOT_A_PROGRAMME = re.compile(
    r"\b(?:grant administration|managed service|licence to practise|"
    r"license to practice|exploratory grants?|innovation grants?|"
    r"teaching and learning innovation|diversity impact programme|"
    r"webinar|newsletter|press release|"
    r"announcement|guidance|how to apply|frequently asked|faq|site ?map)\b",
    re.IGNORECASE,
)

# Providers that are directories or job boards. A record on one of these has no
# provider of its own, which is why the official-source rule refuses them.
_DIRECTORY_PROVIDER = re.compile(
    r"^(?:find a grant|grants? finder|findaphd|find a phd|jobs\.ac\.uk|"
    r"scholarshipbob|wemakescholars|globalscholarships|scholarships?\.com)$",
    re.IGNORECASE,
)

# A name carrying a publication date or a site suffix is a page title, not an
# award name. Publishing it puts "... 2022.5.12 - Tsukuba" in the catalogue.
_DIRTY_NAME = re.compile(
    r"(?:19|20)\d{2}[./-]\d{1,2}[./-]\d{1,2}(?![0-9])|"
    r"\|\s*Study in Japan|\s-\s*[A-Z][\w ]{2,30}$"
)

# Fixture and placeholder names. A test row that reaches the queue must not be
# published just because it is complete: "MEXT Scholarship (Test)" passed every
# gate and would have been served to students.
_TEST_NAME = re.compile(
    r"\((?:test|demo|sample|dummy|fixture)\)|\b(?:lorem ipsum|example scholarship)\b",
    re.IGNORECASE,
)

# A page that announces its own closure. The record may be perfectly extracted;
# publishing it as an open opportunity would be wrong.
_CLOSED_PAGE = re.compile(
    r"\b(?:applications? (?:are |is )?(?:now )?closed|no longer accepting|"
    r"closed for (?:the )?\d{4}|this (?:call|round|cycle) (?:is|has) closed)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AutoDecision:
    """One record's outcome, with the reason a reviewer can audit later."""

    action: str
    code: str
    reason: str

    @property
    def is_decided(self) -> bool:
        return self.action in (APPROVE, REJECT)


def decide(
    *,
    name: str | None,
    provider_name: str | None,
    official_page_url: str | None,
    publishable: bool,
    blocking: list[str],
    name_accepted: bool | None,
    duplicate_of_approved: bool = False,
    page_text: str = "",
) -> AutoDecision:
    """Decide one pending record without reading the page as a human would."""
    if duplicate_of_approved:
        return AutoDecision(
            REJECT,
            "duplicate",
            "an approved record already has this identity",
        )

    from services.domain.source_trust import blocked_source_host

    blocked = blocked_source_host(official_page_url or "")
    if blocked:
        return AutoDecision(
            REJECT,
            "not_official_source",
            f"the record's page is on {blocked}, which is not an official provider source",
        )

    if not (name or "").strip():
        return AutoDecision(REJECT, "no_identity", "the page did not name a programme")

    generic = name_genericities(name)
    if generic:
        return AutoDecision(
            REJECT,
            "generic_name",
            "the name does not identify a programme: " + "; ".join(generic[:2]),
        )

    if _DIRECTORY_PROVIDER.match((provider_name or "").strip()):
        return AutoDecision(
            REJECT,
            "directory_provider",
            f"{provider_name} is a directory or job board, not a provider",
        )

    if _TEST_NAME.search(name):
        return AutoDecision(
            REJECT,
            "test_record",
            "the name marks this as a fixture or placeholder, not a real award",
        )

    if _NOT_A_PROGRAMME.search(name):
        return AutoDecision(
            REJECT,
            "not_a_programme",
            "the name describes administration, news or an institutional grant, not a student award",
        )

    if _DIRTY_NAME.search(name):
        return AutoDecision(
            HOLD,
            "name_hygiene",
            "the name is a page title (publication date or site suffix); needs a clean programme name",
        )

    if name_accepted is False:
        return AutoDecision(
            REJECT,
            "name_rejected",
            "the extractor rejected this candidate name on the page itself",
        )

    if _CLOSED_PAGE.search(page_text or ""):
        return AutoDecision(
            REJECT,
            "closed_cycle",
            "the page states the round is closed; a closed cycle is not an open opportunity",
        )

    if provider_name and _DOMAINISH.match(provider_name.strip()):
        return AutoDecision(
            HOLD,
            "provider_identity",
            f"provider is still a hostname ({provider_name}); needs the organisation name",
        )

    if provider_name and _GENERIC_PROVIDER.match(provider_name.strip()):
        return AutoDecision(
            HOLD,
            "provider_identity",
            f"provider is a batch label ({provider_name}), not an organisation",
        )

    if publishable:
        return AutoDecision(
            APPROVE,
            "passed_all_gates",
            "every publication gate passed with no override",
        )

    return AutoDecision(
        HOLD,
        "incomplete",
        "missing: " + ", ".join(blocking) if blocking else "incomplete record",
    )
