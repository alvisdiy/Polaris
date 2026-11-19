"""Listing guard — a second boundary between page intent and extraction.

``page_intent`` answers *what kind of page is this*. It is good at that, and
V0.1 did not weaken it. What it cannot answer is a narrower question that
V0.1.1 learned the hard way: **does this page describe one opportunity, or
many?**

Two real pages reached the public API in the V0.1 milestone because they
passed page intent and then passed the quality gate:

* ``wemakescholars.com/post-doc-scholarships-...`` — titled "190+ Post Doc
  scholarships 2026-27", linking 78 programmes, its own headings being 78
  individual award names. ``classify_page_intent`` returned
  ``SCHOLARSHIP_DETAIL / 0.75`` because the page carries deadline and
  eligibility *boilerplate*, which the detail rule counts as detail signals.
* ``prospects.ac.uk/postgraduate-recruiters`` — a recruitment *sales* page.
  ``classify_page_intent`` returned ``UNKNOWN / 0.0``, and acquisition
  deliberately extracts UNKNOWN pages, so it reached extraction with no
  funding vocabulary anywhere on it.

This module is that second boundary. It is deterministic, evidence-based, and
returns a **tri-state**, because the failure mode to avoid here is over-
rejecting: a guard that refuses anything it is unsure about turns every
aggregator into a blind spot for the rest of the pipeline.

    HIGH_CONFIDENCE_LISTING  do not extract as one opportunity
    NOT_LISTING             extract normally
    AMBIGUOUS               extract normally, human review decides

``AMBIGUOUS`` deliberately behaves like ``NOT_LISTING``. That is the whole
point of the tri-state: ambiguity must not silently become rejection, or a
conservative-looking guard silently destroys recall.

Design constraints taken from the V0.1 measurement, not from taste:

* **A number alone is never a signal.** "Scholarship 2026", "PhD Studentship:
  Mechanisms Driving Water use in Tree-based Agricultural Systems" and
  "970,000 registrants" all contain digits and all mean different things. Only
  a count that *governs* a funding noun ("190+ Post Doc Scholarships") or a
  listing construction ("Scholarships for Japan") counts.
* **Many links alone is never a signal.** A university detail page legitimately
  carries a large navigation. Link count is only ever used together with
  repeated award-shaped headings.
* **UNKNOWN alone is never a signal.** USTEP is ``UNKNOWN / 0.0`` with zero
  funding mentions and is a real opportunity. What separates it from the
  Prospects sales page is that USTEP's headings *name a programme* and the
  sales page's name metrics.

Every verdict carries the signals that produced it, in the same
``(verdict, evidence)`` shape ``classify_page_intent`` already uses, so the
caller records it in the existing evidence channel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.exploration.page_intent import FUNDING_TERMS, PageIntentResult


class ListingVerdict:
    """The three outcomes. Deliberately not a boolean."""

    HIGH_CONFIDENCE_LISTING = "HIGH_CONFIDENCE_LISTING"
    NOT_LISTING = "NOT_LISTING"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True)
class ListingGuardResult:
    """One verdict, and the signals behind it."""

    verdict: str
    signals: tuple[str, ...] = ()
    detail: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.detail is None:
            object.__setattr__(self, "detail", {})

    @property
    def is_high_confidence_listing(self) -> bool:
        return self.verdict == ListingVerdict.HIGH_CONFIDENCE_LISTING

    @property
    def should_extract(self) -> bool:
        """Whether the page may proceed to extraction.

        Both ``NOT_LISTING`` and ``AMBIGUOUS`` may extract. Only
        ``HIGH_CONFIDENCE_LISTING`` is stopped, which is what keeps recall.
        """
        return not self.is_high_confidence_listing

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "signals": list(self.signals), **self.detail}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


# --------------------------------------------------------------------------
# Signal family A — the page's own title declares a collection
# --------------------------------------------------------------------------

# A count that governs a funding noun: "190+ Post Doc Scholarships",
# "62+ Masters Scholarships", "100 Scholarships", "50+ Fully Funded
# Scholarships".
#
# Two forms are accepted, and the threshold between them is measured, not
# chosen:
#
#   * an explicit ``+``  — "190+", "62+", "436+". The publisher is counting
#     something it cannot be exact about, which is what a listing is.
#   * a bare count of ten or more — "100 Scholarships". Small counts are not
#     a listing signal, because real awards state small numbers: the published
#     "Announcing 3 PhD Studentships within Royal Holloway funded by the AHRC"
#     is one award with three seats, and a count-first pattern rejected it
#     before this threshold existed.
_COUNT_PLUS = re.compile(
    r"\b\d{1,6}\s*\+\s+(?:[a-z]+\s+){0,3}"
    r"(?:scholarships?|fellowships?|bursaries|stipends?|studentships?|awards?|grants?)\b",
    re.I,
)
_COUNT_LARGE = re.compile(
    # 10-999999, with or without thousands separators. Two-digit-prefix
    # alternations such as ``1[0-9]|[2-9][0-9]`` are a trap here: on "100
    # Scholarships" the first branch matches "10" and then the mandatory
    # ``\s+`` fails against "0", so the whole pattern misses. A plain numeric
    # range cannot backtrack into it.
    r"\b[1-9][0-9]{1,5}(?:,[0-9]{3})*\s+(?:[a-z]+\s+){0,3}"
    r"(?:scholarships?|fellowships?|bursaries|stipends?|studentships?|awards?|grants?)\b",
    re.I,
)

# "Scholarships 2026-27", "Scholarships for International Students",
# "Scholarships by degree", "Fully Funded Scholarships".
#
# PLURAL is required and that is load-bearing, not decoration. Measured on the
# stored corpus: Honjo's "Scholarship for Foreign Students | Honjo
# International Scholarship Foundation" is a real award on a page the intent
# classifier calls SCHOLARSHIP_DETAIL, and a singular "Scholarship for ..."
# pattern rejected it. The singular form names one award; only the plural names
# a set.
_LISTING_CONSTRUCTION = re.compile(
    r"\b(?:scholarships|fellowships|bursaries|stipends|studentships|awards|grants)\b"
    r".{0,30}?\b(?:19|20)\d{2}\s*[-–/]\s*(?:19|20)?\d{2}\b"      # year range
    r"|\b(?:scholarships|fellowships|bursaries|stipends)\s+for\b"
    r"|\b(?:scholarships|fellowships|bursaries)\s+by\b",
    re.I,
)

def _quantity_signal(text: str) -> bool:
    """Whether the text states a *count* of awards rather than a year.

    A four-digit number in front of a funding noun is usually a calendar year,
    not a quantity: "2026 Global Korea Scholarship", "2027 Fulbright Grant".
    The count patterns matched those as "2,026 scholarships" and the guard
    refused the page — a live MOFA Korea announcement was rejected this way on
    the 2026-10 run after it had already been classified as one programme.
    Counting 1,900-2,099 of anything is not a shape real pages use.
    """
    for pattern in (_COUNT_PLUS, _COUNT_LARGE):
        for match in pattern.finditer(text):
            digits = re.match(r"\d[\d,]*", match.group(0))
            if not digits:
                continue
            value = int(digits.group(0).replace(",", ""))
            if 1900 <= value <= 2099:
                continue
            return True
    return False


def _family_a_signals(title: str, headings: list[str]) -> list[str]:
    """Signals from the page's own claim about itself.

    Read from the title and the first heading ONLY. Measured on the stored
    corpus: scanning deeper headings rejected
    ``studyinjapan.go.jp/en/planning/scholarships/mext-scholarships/`` — a real,
    already-published scholarship — because a *navigation* heading somewhere in
    the first twenty reads "Scholarships". Every university page has one. The
    page's own claim is its title; its nav menu is not a claim about itself.
    """
    candidates = [_norm(title)]
    if headings:
        candidates.append(_norm(headings[0]))

    found: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        if _quantity_signal(candidate):
            found.append("count_heading")
            break
    for candidate in candidates:
        if not candidate:
            continue
        if _LISTING_CONSTRUCTION.search(candidate):
            found.append("listing_construction_heading")
            break
    return found


# --------------------------------------------------------------------------
# Signal family B — the page's structure is a list
# --------------------------------------------------------------------------

# A heading that names one award: it contains a funding noun and reads like a
# name rather than a sentence fragment. Used to count how many headings on the
# page are individual award names — the aggregator signature.
_AWARD_HEADING = re.compile(
    r"\b(?:scholarships?|fellowships?|bursaries|stipends?|studentships?|awards?|grants?)\b",
    re.I,
)

# A heading that is essentially a figure: "970,000 registrants", "540k magazine
# recipients". A count with no award noun anywhere near it is a metric, and a
# metric is not a scholarship's name.
#
# Trailing punctuation is tolerated because real pages carry it — the stored
# Prospects headings are "970,000 registrants." and "70% uplift." with the full
# stop inside the heading. Anchoring with ``\s*$`` would miss every one of them.
_METRIC_HEADING = re.compile(
    r"^\s*\d[\d,.]*\s*[kKmM]?\s+[a-z]+(?:s)?\s*[.!,]?\s*$"
)

#: How many headings must each name an award before the page is read as a
#: card list. Three would be ambiguous — a detail page can have "Benefits",
#: "Eligibility", "How to apply" style headings that mention awards. Eight is
#: the point where the wemakescholars shape is unmistakable and no single
#: scholarship detail page plausibly reaches it.
_REPEATED_AWARD_HEADINGS = 8

#: Programme-link count that only accompanies genuine card lists. Chosen from
#: the measured data: the wemakescholars page had 78, a university detail page
#: had 1. Deliberately far above any detail page's worth of in-content links.
_LINK_SPIKE = 25


def _family_b_signals(headings: list[str], programme_links: int) -> list[str]:
    found: list[str] = []
    headings = [_norm(h) for h in (headings or [])[:40]]
    headings = [h for h in headings if h]

    award_headings = sum(1 for h in headings if _AWARD_HEADING.search(h))
    if award_headings >= _REPEATED_AWARD_HEADINGS:
        found.append("repeated_award_headings")
    if programme_links >= _LINK_SPIKE:
        found.append("programme_link_spike")
    return found, award_headings  # type: ignore[return-value]


def _metric_heading_signals(
    headings: list[str],
    *,
    programme_links: int,
    funding_mentions: int,
    title_funding_claim: bool,
) -> list[str]:
    """A page whose headings are figures, on a page that claims nothing.

    This is the Prospects shape. It is kept narrow and conjunctive on purpose:
    every one of these conditions alone also holds for real pages, and the
    USTEP calibration case shows that ``UNKNOWN`` plus zero funding mentions is
    *not* sufficient.
    """
    headings = [_norm(h) for h in (headings or [])[:40]]
    headings = [h for h in headings if h]

    metric_headings = [h for h in headings if _METRIC_HEADING.match(h)]
    if not metric_headings:
        return []
    if programme_links:
        return []
    if title_funding_claim:
        return []
    if funding_mentions:
        return []
    return ["metric_heading_no_opportunity_claim"]


# --------------------------------------------------------------------------
# The guard
# --------------------------------------------------------------------------

def classify_listing_page(
    *,
    page_title: str = "",
    headings: list[str] | None = None,
    anchors: list[str] | None = None,
    text: str = "",
    intent: PageIntentResult | None = None,
) -> ListingGuardResult:
    """Decide whether this page must not be extracted as one opportunity.

    Takes the already-computed ``intent`` result rather than re-deriving it —
    one classifier, one fetch, one verdict to record.
    """
    headings = headings or []
    title = _norm(page_title)
    programme_links = intent.programme_links if intent else 0
    funding_mentions = intent.funding_mentions if intent else 0
    title_funding_claim = bool(
        (intent.signals or {}).get("title_funding_claim") if intent else False
    )
    if not intent and (title or headings):
        # Standalone use (tests, tooling). Recompute the two counts the guard
        # needs from the page-intent helpers rather than reimplementing them.
        from services.exploration.page_intent import programme_link_count

        programme_links = programme_link_count(list(anchors or []))
        body = (text or "")[:20000].casefold()
        funding_mentions = len([t for t in FUNDING_TERMS if t and t in body])
        title_funding_claim = any(t in title.casefold() for t in FUNDING_TERMS)

    signals: list[str] = []
    signals += _family_a_signals(title, headings)
    family_b, award_headings = _family_b_signals(headings, programme_links)
    signals += family_b
    signals += _metric_heading_signals(
        headings,
        programme_links=programme_links,
        funding_mentions=funding_mentions,
        title_funding_claim=title_funding_claim,
    )

    # Defence in depth: acquisition already skips these before extraction, but
    # a caller using the guard standalone should not be able to shoot itself in
    # the foot by extracting an index.
    if intent is not None and intent.is_discovery_surface:
        signals.append(f"page_intent_discovery_surface:{intent.intent}")

    detail = {
        "title": title[:200],
        "programme_links": programme_links,
        "award_headings": award_headings,
        "funding_mentions": funding_mentions,
    }

    if "count_heading" in signals or "listing_construction_heading" in signals:
        return ListingGuardResult(ListingVerdict.HIGH_CONFIDENCE_LISTING, tuple(signals), detail)

    if "repeated_award_headings" in signals and "programme_link_spike" in signals:
        return ListingGuardResult(ListingVerdict.HIGH_CONFIDENCE_LISTING, tuple(signals), detail)

    if "metric_heading_no_opportunity_claim" in signals:
        return ListingGuardResult(ListingVerdict.HIGH_CONFIDENCE_LISTING, tuple(signals), detail)

    if any(s.startswith("page_intent_discovery_surface") for s in signals):
        return ListingGuardResult(ListingVerdict.HIGH_CONFIDENCE_LISTING, tuple(signals), detail)

    # Weak hints alone are not enough to stop a page. Report them and let the
    # existing review flow decide — this is the AMBIGUOUS case, and it must
    # keep extracting.
    weak = [s for s in signals if s in ("repeated_award_headings", "programme_link_spike")]
    verdict = ListingVerdict.AMBIGUOUS if weak else ListingVerdict.NOT_LISTING
    return ListingGuardResult(verdict, tuple(signals), detail)


REASON = "LISTING_PAGE_DETECTED"


class ListingGuard:
    """Namespace for the guard's constants.

    Exists so callers refer to one name rather than importing a bare string
    that a typo would silently turn into an unrecorded skip.
    """

    REASON = REASON
    HIGH_CONFIDENCE_LISTING = ListingVerdict.HIGH_CONFIDENCE_LISTING
    NOT_LISTING = ListingVerdict.NOT_LISTING
    AMBIGUOUS = ListingVerdict.AMBIGUOUS

    @staticmethod
    def check(**kwargs) -> ListingGuardResult:
        return classify_listing_page(**kwargs)
