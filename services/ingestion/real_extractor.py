"""Deterministic extraction client using heuristic parsing."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import urldefrag, urljoin, urlsplit

from services.domain.degree_levels import declared_award_levels
from services.domain.vocabulary import DEGREE, FUNDING_TYPE
from services.exploration.url_utils import domain_of, registered_domain
from services.ingestion.extraction_quality import (
    ExtractionVerdict,
    normalize_scholarship_name,
    score_candidate_name,
)
from services.ingestion.extractor import LLMClient


def _relative_date(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


# Fragments that the organizational-phrase patterns can match but which are
# not organization names. This is a *rejection* set for over-eager matches,
# not a list of expected providers.
_GENERIC_PROVIDER_REJECTS = {
    "the",
    "this",
    "these",
    "our",
    "your",
    "their",
    "it",
    "they",
    "we",
    "you",
    "us",
    "everyone",
    "anyone",
    "someone",
    "students",
    "applicants",
    "international students",
    "all students",
    "the applicant",
    "participants",
    "government of",
    "ministry of",
    "department of",
    # Category words that head a section rather than name an organisation.
    # "Other Scholarships and Tuition Fee Reductions Systems" is a heading on
    # Study in Japan; "Other" is not the organisation behind it, and a
    # Provider row called "Other" would be indistinguishable from a real one.
    "other",
    "others",
    "various",
    "all",
    "more",
    "general",
    "misc",
    "miscellaneous",
    "additional",
    "external",
    "internal",
    "public",
}


# A sentence boundary inside a candidate: punctuation, whitespace, and then a
# new capitalised word. A provider is a noun phrase, so anything past the first
# of these belongs to the sentence *after* the name, not to the name.
_SENTENCE_BREAK = re.compile(r"[.;:!?,]\s+(?=[A-Z0-9])")


# Words that make a nearby term a *qualification* rather than an incidental
# mention of one.
_DEGREE_CONTEXT_NOUN = r"(?:degree|programme|program|course|studies|study|level|qualification)"

# Words that make a nearby term a statement about *funding* rather than an
# incidental use of the same adjective.
_FUNDING_CONTEXT_NOUN = (
    r"(?:funding|funded|scholarship|scholarships|grant|grants|fee|fees|waiver"
    r"|tuition|award|awards|support|cover|coverage|stipend|stipends|allowance)"
)

# Nouns that attribute funding to the *award*. Deliberately narrower than
# `_FUNDING_CONTEXT_NOUN`: "cover" and "coverage" belong there because the
# alias path needs them, but here they are what a *loan* does ("a loan can
# cover tuition fees"), and admitting them would record a student's own
# borrowing as the scholarship's funding evidence.
# Words that can sit between a deadline keyword and its date.
#
# "deadline is 3 May 2027", "deadline remains 1 June 2027" and — the one
# that matters for Priority D — "the application deadline has been extended
# to 31 January 2027". Without this the second of those is invisible, which
# is exactly how a page contradicts itself unnoticed.
_DEADLINE_LINK = (
    r"(?:(?:is|was|has\s+been|have\s+been|had\s+been|will\s+be|remains|"
    r"extended|postponed|revised|updated|amended|changed|moved|shifted|"
    r"pushed\s+back|now|to|:)\s*)*"
)


# Deadline patterns, ordered most specific first.
#
# Kept at module level and explicitly compiled so `_deadline_candidates`
# (which needs every match) and `_extract_deadline` (which needs the first)
# cannot drift apart — M10 found that class of drift twice in this file, and
# hoisting the list broke it a third time until the pieces were joined here
# rather than by implicit adjacency.
_KEYWORD = (
    r"(?:deadline|application deadline|apply by|due date|closing date"
    r"|closes on|applications?\s+close[sd]?"
    # The same field in the languages Polaris crawls. Without these, a Malay
    # "Tarikh tutup permohonan" and a German "Bewerbungsschluss" page state a
    # deadline that the extractor cannot see.
    r"|tarikh\s+tutup[a-z ]{0,20}|tempoh\s+permohonan|permohonan\s+tutup"
    r"|bewerbungsschluss|bewerbungsfrist|anmeldeschluss)"
)
_MONTH_FIRST = r"([^\W\d_]{3,12}\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})"
_DAY_FIRST = r"(\d{1,2}(?:st|nd|rd|th)?\.?\s+[^\W\d_]{3,12}\s+\d{4})"


def _deadline(pattern: str):
    """Compile a deadline pattern.

    The flag lives here because both matchers call `.search()` /
    `.finditer()` on the compiled object rather than going through
    `re`, so a flag passed at the call site is no longer possible.
    """
    return re.compile(pattern, re.IGNORECASE)


# Words that legitimately sit between a deadline keyword and its date in real
# pages, without changing what the sentence means:
#
#   "Deadline: Friday 4 December 2026."
#   "apply by 1pm (UK time) on Monday 1 June 2026"
#   "deadline of 5pm (UK time) on Monday 22 March 2027"
#   "deadline - 15 December 2026"
#
# Before this, the extractor only accepted ``[:\s]+`` there, so every one of
# those pages was recorded as "no deadline published" — 74 of 99 approved
# records. The vocabulary is closed on purpose: the filler is weekdays, clock
# times, timezone notes and small function words only. Free text between the
# keyword and a date is exactly how "deadline, i.e. have defended their PhD
# thesis between December 2021 and December 2026" would be misread as a
# deadline of December 2021.
_DEADLINE_FILLER = (
    r"(?:\s|[,:.\-–—()]|"
    r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|nesday|rsday|urday|sday)?\.?|"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|"
    r"(?:noon|midday|midnight)|"
    r"(?:uk|gmt|bst|cet|local|china|japan)\s*time|"
    r"(?:the|of|on|at|by|before|until|to|is|for|and)\b|"
    # "The deadline for applications is 5 June 2027", "deadline of application:
    # 31 July 2025", "the deadline for submitting materials is December 15".
    r"(?:applications?|applying|apply|submissions?|submitting|submit|materials?|"
    r"nomination|nominating|online|date|programmes?|programs?|courses?|study|"
    r"in|update[sd]?)\b|"
    r"\((?![^)]*\d)[^)]{0,25}\)|"
    r"\d{1,2}:\d{2}|"
    r"(?:no\s+later\s+than|not\s+later\s+than)"
    r")"
)

# How far the date may sit from its keyword. The filler is bounded both by
# repetition count and by this distance, because two guards fail differently:
# the count stops a long run of single words, the distance stops a few long
# tokens from reaching across a clause.
_DEADLINE_MAX_GAP = 90


def _deadline_gap_ok(match: "re.Match[str]") -> bool:
    """Whether the captured date is close enough to the keyword to belong to it."""
    return (match.start(1) - match.start()) <= _DEADLINE_MAX_GAP


_DEADLINE_PATTERNS = [
    # "deadline: May 15, 2024" | "apply by: June 1st, 2024"
    _deadline(_KEYWORD + r"[:\s]+" + _MONTH_FIRST),
    # "deadline: 2024-05-15" | "apply by 2024/05/15"
    _deadline(r"(?:deadline|application deadline|apply by)[:\s]+(\d{4}[-/]\d{2}[-/]\d{2})"),
    # "May 15, 2024 deadline" | "June 1, 2024 application"
    _deadline(_MONTH_FIRST + r".*?(?:deadline|due|application)"),
    # "15 December 2026: Application deadline" — the day-first spelling of the
    # same shape, which a calendar-style page prints above the label rather
    # than after it. Bounded to one short clause so a date at the top of a
    # page cannot borrow a deadline word from a paragraph further down.
    _deadline(_DAY_FIRST + r"[^\n.]{0,40}?(?:deadline|due date|closing date)"),
    # "15 May 2024" | "1st June 2024"
    _deadline(r"(?:deadline|application deadline|apply by)[:\s]+" + _DAY_FIRST),
    # "by 15.05.2024" | "until 01.06.2024"
    _deadline(r"(?:by|until|deadline)[:\s]+(\d{1,2}\.\d{2}\.\d{4})"),
    # Standalone dates near context words
    _deadline(r"(?:accept.*?until|period.*?to)[:\s]+" + _MONTH_FIRST),
    # A linking phrase between the keyword and the date: "Application deadline
    # is 3 May 2027" is how a British university writes it, and "the
    # application deadline has been extended to 31 January 2027" is how a
    # page changes its mind in public. Only the second of those is a second
    # deadline, and without it Priority D has nothing to detect.
    _deadline(_KEYWORD + r"\s+" + _DEADLINE_LINK + _MONTH_FIRST),
    _deadline(_KEYWORD + r"\s*" + _DEADLINE_LINK + _DAY_FIRST),
    # Portal pages render "Deadline: 09 Dec 2025" as a definition list,
    # which trafilatura collapses to "Deadline09 Dec 2025" with no
    # separator at all. Allowing a couple of stray non-word characters
    # recovers the date without loosening anything else: the date
    # itself still has to parse.
    _deadline(_KEYWORD + r"\W{0,3}" + _DAY_FIRST),
    _deadline(_KEYWORD + r"\W{0,3}" + _MONTH_FIRST),
    # The same two shapes with weekday / time / timezone / connector filler in
    # between. Ordered last so a tighter pattern still wins when both match.
    _deadline(_KEYWORD + _DEADLINE_FILLER + r"{0,40}" + _DAY_FIRST),
    _deadline(_KEYWORD + _DEADLINE_FILLER + r"{0,40}" + _MONTH_FIRST),
    # "new deadline (update: 28/04/2026)" — day-first when the day cannot be a
    # month, month-first when only that reading is possible, and nothing at all
    # when 03/04/2026 could be either.
    _deadline(_KEYWORD + _DEADLINE_FILLER + r"{0,40}(\d{1,2}/\d{1,2}/\d{4})"),
    # "reopened ... with a new deadline in May (update: 28/04/2026)": the
    # operative date is the one the page attached to its own correction.
    _deadline(
        _KEYWORD + r"[^.\n]{0,40}?(?:update[sd]?|revised|new deadline)"
        r"[^.\n]{0,20}?[:(]?\s*(\d{1,2}/\d{1,2}/\d{4})"
    ),
]

# Wording that says one date replaces an earlier one. When a page says the
# deadline "has been extended", it has resolved its own contradiction and the
# later date is the operative one; recording a conflict there would send a
# reviewer to a question the page already answered.
_SUPERSESSION_MARKER = (
    r"(?:extended|postponed|revised|updated|amended|changed\s+to|new\s+deadline"
    r"|moved\s+to|rescheduled|代替|変更|延期)"
)


def _sentence_around(text: str, start: int, end: int, limit: int = 200) -> str:
    """The clause containing a match, for storing as conflict evidence."""
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start), text.rfind(";", 0, start))
    right_candidates = [p for p in (text.find(".", end), text.find("\n", end), text.find(";", end)) if p != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return " ".join(text[left + 1 : right].split())[:limit]


_FUNDING_EVIDENCE_CONTEXT_NOUN = (
    r"(?:funding|funded|scholarship|scholarships|grant|grants|award|awards"
    r"|benefit|benefits|support|value|provides|provided|covers)"
)
_UNMAPPED_FUNDING_PATTERNS = (
    r"all\s+(?:the\s+)?tuition\s+fees[^.;]{0,60}",
    r"tuition\s+fees?[^.;]{0,40}(?:travel|living|accommodation)[^.;]{0,40}",
    r"(?:travel|travels|airfare)\s+and\s+living\s+costs?",
    r"full\s+tuition\s+(?:and\s+\w+\s+)?(?:living|travel)",
)


def _word_bounded(text: str, phrase: str):
    """Every occurrence of `phrase` in `text` as whole words, not substrings.

    A bare substring test finds "full" inside "full-time" and "exchange"
    inside "exchange rate", both of which are about something else entirely.
    """
    return re.finditer(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text)


# Qualification abbreviations that name themselves. "a Ph.D." or "an MSc" is
# a statement of level whatever follows it, so these do not need a nearby
# qualification noun to count.
_SELF_DECLARING_DEGREE_ALIASES = frozenset({"ph.d", "ph.d.", "phd", "msc", "b.sc.", "m.sc.", "bsc"})


def _is_self_describing(alias: str, context_noun: str) -> bool:
    """Whether the phrase declares its own subject.

    "tuition waiver" is a statement about funding whatever it sits next to,
    and so is "exchange programme". Requiring a neighbouring noun for these
    would drop the clearest statements in the vocabulary; requiring one for
    bare words like "full" or "postgraduate" is what stops "full-time" and
    "postdoctoral scholars" from being read as funding and degree claims.
    """
    return bool(re.search(context_noun, alias))


def _longest_alias_match(lowered: str, vocabulary, *, context_noun: str = "") -> tuple[str, str] | None:
    """The most specific alias the page used, as ``(alias, canonical)``.

    Two rules, both learned the hard way from real pages:

    **Longest wins.** "full tuition waiver" contains both "full"
    (→ Fully Funded) and "tuition waiver" (→ Tuition Only); declaration order
    reported a scholarship as fully funded when the page had said its tuition
    was waived. A shorter phrase inside a longer one is the weaker signal.

    **The phrase has to be about its own subject.** With `context_noun`, an
    alias only counts when it stands next to the noun it describes — "full"
    next to "funding" is a funding claim, "full-time" is an enrolment
    condition. Without that, "Funding value up to £10,000" was reported as
    Fully Funded because the page also said "full-time MSc programmes".
    """
    matches: list[tuple[str, str]] = []
    for alias, canonical in vocabulary.aliases.items():
        for match in _word_bounded(lowered, alias):
            if not context_noun:
                matches.append((alias, canonical))
                continue
            before = lowered[max(0, match.start() - 30) : match.start()]
            after = lowered[match.end() : match.end() + 30]
            if (
                alias == canonical.casefold()
                or _is_self_describing(alias, context_noun)
                or re.search(context_noun + r"$", before)
                or re.match(r"\s*" + context_noun, after)
            ):
                matches.append((alias, canonical))
    if not matches:
        return None
    return max(matches, key=lambda pair: len(pair[0]))


def _declared_degree_levels(lowered: str) -> set[str]:
    """Canonical levels the page states *as the level of study*.

    A bare substring search returned whichever level appeared first in the
    declaration order, so a page that merely mentioned an exchange programme
    was published with ``degree = Exchange``, and one that said
    "postdoctoral scholars" was published with ``PhD``. A level only counts
    when a qualification noun follows it: "Master's degree", "doctoral
    programme", "exchange programme".
    """
    found: set[str] = set()
    for alias, canonical in DEGREE.aliases.items():
        if alias in _SELF_DECLARING_DEGREE_ALIASES:
            # `next(...)` rather than the iterator itself: a generator object
            # is always truthy, which would make every alias match.
            if next(_word_bounded(lowered, alias), None) is not None:
                found.add(canonical)
            continue
        pattern = re.escape(alias) + r"(?:['’]s)?\s+" + _DEGREE_CONTEXT_NOUN
        if re.search(pattern, lowered):
            found.add(canonical)
        elif _is_self_describing(alias, _DEGREE_CONTEXT_NOUN) and next(_word_bounded(lowered, alias), None) is not None:
            # "exchange programme", "short course": the phrase states its own
            # subject, so it does not also need a neighbouring noun.
            found.add(canonical)
    return found


def _truncate_at_sentence(candidate: str) -> str:
    """Cut a captured phrase back to the first complete noun phrase.

    Applied to every provider candidate regardless of which pattern matched,
    because the patterns disagree about where an organisation name ends: one
    stopped at a comma, another ran three words past a full stop. Rather than
    tuning each alternation, the boundary is defined once here — an
    organisation name ends at the first sentence break, and whatever follows
    is prose that happened to be adjacent to it.
    """
    return _SENTENCE_BREAK.split(candidate, maxsplit=1)[0].strip(" .,:;-")


# Precedence between kinds of evidence that a page names one programme.
#
# A heading is the page's own statement of its subject. A raw page title is
# that statement plus whatever the publishing CMS appended. A link label is a
# statement about a *different* page, so it ranks below both and, on its own,
# is not a self-claim at all. Ranking on raw confidence alone put a link label
# above the heading often enough to extract "Application procedure &
# deadlines" from a Fulbright programme page and "Polytechnic Foundation
# Programme (PFP)" from a page about TP Engineering scholars 2026.
#
# Lower is better. `_TIER_SELF_CLAIM` is the boundary: a page with nothing
# above it has not claimed to be about one programme at all.
_TIER_TITLE_AND_HEADING = 0
_TIER_HEADING = 1
_TIER_TITLE = 2
_TIER_ANCHOR = 3
_TIER_SELF_CLAIM = 3


def _claim_tier(in_title: bool, in_heading: bool, in_anchor: bool) -> int:
    """Which kind of evidence put this candidate on the page."""
    if in_heading and in_title:
        return _TIER_TITLE_AND_HEADING
    if in_heading:
        return _TIER_HEADING
    if in_title:
        return _TIER_TITLE
    if in_anchor:
        return _TIER_ANCHOR
    return 4


class DeterministicLLMClient(LLMClient):
    """Parse clean text to extract scholarship data using heuristics.

    This client uses pattern matching to extract dates, requirements, and benefits
    from trafilatura-cleaned text. It does not call external LLM APIs.
    Fields that cannot be determined are left as None.

    M9: name extraction no longer regexes prose. Candidates are drawn from
    the page's structural context (title, headings, anchors) and each is
    judged by ``extraction_quality``. When nothing is confident the result
    is ``name=None`` with a low confidence — an explicit "we do not know",
    never a fabricated placeholder that would flow into the Knowledge Base.

    M9.1 Phase 4: categorical values are normalised through
    ``services.domain.vocabulary``. When the page states a qualification the
    domain has no category for (a polytechnic diploma, a foundation
    programme), the value is left None and ``last_unmapped_qualification``
    records the source wording as evidence — see ADR-016.
    """

    # Source terminology seen during the most recent extraction that Polaris
    # deliberately does not map to a degree level. Evidence for the reviewer,
    # never a value written to the record.
    last_unmapped_qualification: str | None = None

    # Levels the page mentioned when more than one was declared, so a
    # reviewer sees which readings were available rather than only that the
    # field came back empty.
    last_degree_candidates: list[str] = []

    def __init__(self, default_country: str | None = "JP") -> None:
        # Country exploration supplies a source-country fallback. Aggregator
        # ingestion passes None because country is unknown at discovery time.
        self.default_country = default_country

    # ---- name extraction (M9) -----------------------------------------

    @staticmethod
    def _markdown_headings(clean_text: str) -> list[str]:
        """Markdown ``#``/``##`` headings, when the text carries any.

        trafilatura can emit markdown-shaped text, and callers that hold only
        a cleaned string (no parsed HTML) still deserve heading context. This
        is genuine structural evidence, so it counts as a heading rather than
        as prose.
        """
        return [
            " ".join(line.lstrip("#").split())
            for line in (clean_text or "").splitlines()
            if line.lstrip().startswith("#") and len(line.lstrip("#").strip()) > 3
        ][:12]

    def _candidate_names(self, clean_text: str, page_title: str, headings, anchors) -> tuple[list[str], set[str]]:
        """Structural candidates first, prose patterns only as a last resort.

        Returns ``(candidates, markdown_headings)`` so the caller can award
        heading credit to strings that were proven to be headings here.
        """
        candidates: list[str] = []
        md_headings = self._markdown_headings(clean_text)

        for h in list(headings or [])[:12]:
            candidates.append(h)
        for h in md_headings:
            candidates.append(h)

        if page_title:
            # "MEXT Scholarship | Study in Japan" -> try the full title and
            # each side of common separators. All are judged, not trusted.
            candidates.append(page_title)
            for sep in (" | ", " - ", " :: ", " |"):
                if sep in page_title:
                    for part in page_title.split(sep):
                        candidates.append(part)

        # Anchors are weaker evidence but on a portal listing page the
        # scholarship name often appears only as a link label.
        for a in (anchors or [])[:40]:
            if 12 <= len(a) <= 160:
                candidates.append(a)

        # Prose patterns are a last resort for pages with no usable structure.
        if not candidates:
            for p in (r"([A-Z][A-Za-z\s]{6,80}(?:Scholarship|Grant|Fellowship|Program|Programme))",):
                for m in re.finditer(p, clean_text or "", re.MULTILINE):
                    candidates.append(m.group(1).strip())

        seen: set[str] = set()
        unique: list[str] = []
        for c in candidates:
            key = normalize_scholarship_name(c or "")
            if key and key not in seen:
                seen.add(key)
                unique.append(c)
        return unique, {normalize_scholarship_name(h) for h in md_headings}

    def _extract_name_verdict(
        self,
        clean_text: str,
        page_title: str = "",
        headings: tuple = (),
        anchors: tuple = (),
        looks_like_index: bool = False,
    ) -> ExtractionVerdict:
        """Best name candidate, or an explicit 'not identifiable' verdict."""
        headings = list(headings or [])
        anchors = list(anchors or [])
        title_key = normalize_scholarship_name(page_title or "")
        candidates, md_heading_keys = self._candidate_names(clean_text, page_title, headings, anchors)
        heading_keys = {normalize_scholarship_name(h) for h in headings} | md_heading_keys
        anchor_keys = {normalize_scholarship_name(a) for a in anchors}

        best: ExtractionVerdict | None = None
        best_tier = -1
        self_claim_reasons: list[str] = []
        for candidate in candidates:
            key = normalize_scholarship_name(candidate)
            in_title = bool(title_key) and key == title_key
            in_heading = key in heading_keys
            tier = _claim_tier(in_title, in_heading, key in anchor_keys)
            verdict = score_candidate_name(
                candidate,
                in_title=in_title,
                in_heading=in_heading,
                in_anchor=key in anchor_keys,
                page_is_portal_index=looks_like_index,
                corpus_support=(1 if key in heading_keys else 0) + (1 if key in anchor_keys else 0),
            )
            if not verdict.accepted:
                if tier < _TIER_SELF_CLAIM and not self_claim_reasons:
                    self_claim_reasons = verdict.reasons
                continue
            if tier < _TIER_SELF_CLAIM:
                # Lower tier wins, so the tier is negated before the comparison.
                # Confidence only breaks ties within one tier — a stronger claim
                # about a link label must never outrank the page's own heading.
                if best is None or (-tier, verdict.confidence) > (-best_tier, best.confidence):
                    best, best_tier = verdict, tier
            elif best is None:
                best, best_tier = verdict, tier

        if best is None or best_tier >= _TIER_SELF_CLAIM:
            # Either nothing was found, or every candidate that survived the
            # gate was a link label. In both cases the page never claimed to be
            # about a named programme, so naming one of the things it links to
            # would attribute another page's scholarship to this page. NULL
            # routes the record to review; a plausible-looking name does not.
            return ExtractionVerdict(
                False,
                0.0,
                self_claim_reasons or ["no name candidate found on page"],
                None,
            )
        return best

    def _extract_cycle(self, text: str) -> Optional[str]:
        """Extract the scholarship cycle/cohort label (e.g. "2027", "AY2027/28").

        Only explicit cohort phrasing counts. A bare year on the page is not
        a cycle — inventing one would conflate cycle with deadline.
        """
        patterns = [
            # The year alternation is ordered longest-first on purpose.
            # "\d{2}|20\d{2}" against "2026/2027" matches "20" and yields
            # "2026-20", which is a truncated label that reads as a real
            # cohort and is indistinguishable from one once stored.
            r"(?:academic year|a\.?y\.?)\s*:?\s*(20\d{2}\s*[-/]\s*(?:20\d{2}|\d{2}))",
            r"(20\d{2})\s*(?:intake|cohort|cycle)",
            r"(?:intake|cohort|cycle)\s*(?:of|for|:)?\s*(20\d{2})",
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return re.sub(r"\s*([-/])\s*", r"\1", m.group(1).strip())
        return None

    def _deadline_candidates(self, text: str) -> list[dict]:
        """Every date the page states *as the deadline*, with its evidence.

        `_extract_deadline` returns the first of these it finds, which is the
        right answer when there is only one and the wrong one when the page
        contradicts itself. This method exists so the caller can see the whole
        set and decide, rather than being handed one arbitrary member of it.
        """
        candidates: list[dict] = []
        seen: set[str] = set()
        for pattern in _DEADLINE_PATTERNS:
            for match in pattern.finditer(text):
                if not _deadline_gap_ok(match):
                    continue
                normalized = self._normalize_date(match.group(1).strip())
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                sentence = _sentence_around(text, match.start(), match.end())
                candidates.append(
                    {
                        "value": normalized,
                        "sentence": sentence,
                        "supersedes": bool(
                            re.search(
                                _SUPERSESSION_MARKER,
                                text[max(0, match.start() - 90) : match.end() + 30],
                                re.IGNORECASE,
                            )
                        ),
                    }
                )
        return candidates

    def _extract_deadline(self, text: str) -> Optional[str]:
        """Extract and normalize deadline to ISO YYYY-MM-DD format.

        Supports formats: Month DD, YYYY | DD Month YYYY | YYYY-MM-DD | YYYY/MM/DD | DD.MM.YYYY
        """
        for pattern in _DEADLINE_PATTERNS:
            m = next(
                (candidate for candidate in pattern.finditer(text) if _deadline_gap_ok(candidate)),
                None,
            )
            if m:
                date_str = m.group(1).strip()
                normalized = self._normalize_date(date_str)
                if normalized:
                    return normalized
        return None

    def _resolve_deadline(self, text: str) -> tuple[Optional[str], dict | None]:
        """The deadline to store, and the contradiction (if any) behind it.

        M10 recorded the behaviour as "effectively first-match": a page saying
        "applications close 15 January" and, further down, "the application
        deadline has been extended to 31 January" produced 15 January, and the
        second statement was silently discarded. Storing the first date is a
        guess presented as a fact, and it is the guess that makes a student
        apply late.

        Two outcomes, decided by what the page says rather than by position:

        - **The page resolves itself.** Exactly one candidate carries a
          supersession marker ("extended", "postponed", "revised"). That date
          is operative and is what gets stored; every candidate is kept on the
          record so the change is auditable. No conflict is raised, because
          there is no question left for a reviewer to settle.

        - **The page contradicts itself.** Otherwise nothing is stored — not
          the first date, not the last — and a conflict is recorded in the
          shape ``services.review.quality._conflict_map`` already understands.
          That marks the field CONFLICTING, which routes it to review and
          blocks publication. No new subsystem: it is the mechanism M9 built.
        """
        candidates = self._deadline_candidates(text)
        if len(candidates) < 2:
            return self._extract_deadline(text), None

        superseding = [c for c in candidates if c["supersedes"]]
        evidence = [
            {
                "value": c["value"],
                "sentence": c["sentence"],
                "supersedes": c["supersedes"],
            }
            for c in candidates
        ]
        if len(superseding) == 1:
            return superseding[0]["value"], {
                "field": "application_deadline",
                "resolved": True,
                "resolution": "the page names a replacement for an earlier deadline",
                "values": evidence,
            }

        return None, {
            "field": "application_deadline",
            "resolved": False,
            "reason": (
                f"the page states {len(candidates)} different application deadlines and does not say which one applies"
            ),
            "values": evidence,
        }

    # Month names dateutil cannot read without a locale. Polaris crawls pages in
    # Malay, Indonesian and German, where "31 Disember 2026" and "8 Oktober 2025"
    # are ordinary spellings; without this they parse as nothing at all.
    _MONTH_NAMES = {
        "januari": "January", "februari": "February", "maret": "March",
        "mei": "May", "juni": "June", "juli": "July", "agustus": "August",
        "oktober": "October", "desember": "December", "disember": "December",
        "januar": "January", "februar": "February", "märz": "March",
        "maerz": "March", "dezember": "December", "okt": "October",
        "dez": "December", "jan": "January", "feb": "February", "mär": "March",
        "apr": "April", "jun": "June", "jul": "July", "aug": "August",
        "sep": "September", "sept": "September", "nov": "November",
    }

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """Normalize various date formats to ISO YYYY-MM-DD."""
        try:
            from dateutil import parser

            # Ambiguous slash dates are refused rather than guessed: 03/04/2026
            # is two different days depending on the writer's country.
            slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", date_str.strip())
            if slash:
                first, second, year = (int(part) for part in slash.groups())
                if first > 12 and second <= 12:
                    return f"{year:04d}-{second:02d}-{first:02d}"
                if second > 12 and first <= 12:
                    return f"{year:04d}-{first:02d}-{second:02d}"
                return None

            for native, english in self._MONTH_NAMES.items():
                date_str = re.sub(rf"\b{native}\b", english, date_str, flags=re.IGNORECASE)

            # Remove ordinal suffixes (1st -> 1, 2nd -> 2)
            cleaned = re.sub(r"(\d+)(?:st|nd|rd|th)", r"\1", date_str)
            # DD.MM.YYYY pattern - use dayfirst=True to avoid month/day swap
            if re.match(r"\d{1,2}\.\d{2}\.\d{4}", cleaned):
                parsed = parser.parse(cleaned, dayfirst=True, fuzzy=False)
            else:
                parsed = parser.parse(cleaned, fuzzy=False)
            return parsed.strftime("%Y-%m-%d")
        except Exception:
            return None

    def _extract_gpa(self, text: str) -> float | None:
        m = re.search(r"(?:GPA|gpa)[:\s]+(\d+\.?\d*)", text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
        return None

    def _extract_age_limit(self, text: str) -> int | None:
        m = re.search(r"(?:under|age limit|below)[:\s]*(\d{2})", text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return None

    def _extract_toefl(self, text: str) -> tuple[bool, int | None]:
        m = re.search(r"TOEFL[:\s]+(\d{2,3})", text, re.IGNORECASE)
        if m:
            return (True, int(m.group(1)))
        return (False, None)

    # Negation cues that turn a benefit keyword into a statement that the
    # benefit is NOT provided: "tuition is not covered", "no accommodation
    # is provided", "travel must be borne by the student". A bare keyword
    # search recorded all of those as covered benefits.
    _BENEFIT_NEGATION_BEFORE = re.compile(
        r"(?:\bnot\b|\bno\b|\bnever\b|\bwithout\b|does\s+not|do\s+not|is\s+not"
        r"|are\s+not|will\s+not|shall\s+not|cannot|excluded|borne\s+by"
        r"|own\s+expense|self[-\s]?fund\w*)[^.;]{0,40}$"
    )
    _BENEFIT_NEGATION_AFTER = re.compile(
        r"^[^.;]{0,40}?(?:\bnot\b\s+(?:be\s+)?(?:covered|included|provided|paid)"
        r"|is\s+excluded|are\s+excluded|must\s+be\s+borne|at\s+(?:their|the\s+student|your)\s+own\s+expense)"
    )

    def _benefit_mentioned(self, text_lower: str, pattern: str) -> bool:
        """True when a benefit keyword appears in a non-negated context."""
        for m in re.finditer(pattern, text_lower):
            before = text_lower[max(0, m.start() - 60):m.start()]
            after = text_lower[m.end():m.end() + 50]
            if self._BENEFIT_NEGATION_BEFORE.search(before):
                continue
            if self._BENEFIT_NEGATION_AFTER.search(after):
                continue
            return True
        return False

    def _extract_benefits(self, text: str) -> Dict[str, bool]:
        text_lower = text.lower()
        return {
            "tuition_fee": self._benefit_mentioned(text_lower, r"tuition"),
            "monthly_allowance": self._benefit_mentioned(text_lower, r"monthly\s+(allowance|stipend)"),
            "accommodation": self._benefit_mentioned(text_lower, r"accommodation|housing"),
            "health_insurance": self._benefit_mentioned(text_lower, r"health\s+insurance|medical"),
            "travel_ticket": self._benefit_mentioned(text_lower, r"(?:round-?trip|airfare|flight|travel)"),
            "research_grant": self._benefit_mentioned(text_lower, r"research\s+grant"),
        }

    def _extract_research_experience(self, text: str) -> str | None:
        """Research-experience level, only from an explicit statement.

        Previously any page containing the word "research" (i.e. nearly
        every university page) was recorded as research experience
        "Preferred" — a fabricated requirement that then fed matching.
        """
        text_lower = text.lower()
        if re.search(
            r"research\s+experience[^.;]{0,30}?(required|mandatory|essential|must)",
            text_lower,
        ) or re.search(r"(required|mandatory|must)[^.;]{0,30}?research\s+experience", text_lower):
            return "Required"
        if re.search(
            r"research\s+experience[^.;]{0,30}?(preferred|desirable|advantage|asset|plus)",
            text_lower,
        ) or re.search(
            r"(preferred|desirable|advantageous|an\s+advantage)[^.;]{0,40}?research\s+experience",
            text_lower,
        ):
            return "Preferred"
        return None

    # ----------------------------------------------------------------------
    # Heuristic extraction for fields required by validation but not covered
    # ----------------------------------------------------------------------
    def _extract_provider_name(self, text: str, page_title: str = "") -> str | None:
        """Find the offering organization in the page text.

        M8 matched a hardcoded list of nine organisation names, which meant
        any provider not on that list fell through to ``by <words>`` — which
        is how names like ``Nus``, ``Hisf`` and ``Sp`` entered the Provider
        table. Detection is now structural (organizational keywords) and the
        result is short and title-case; an unrecognised page returns None and
        the caller resolves the provider from the SourceRegistry row instead.
        """
        # Phrases that introduce the organisation offering the opportunity.
        patterns = [
            # `.` and `,` are excluded from the capture so a match cannot run
            # past a sentence boundary: "Administered by Temasek Polytechnic.
            # The Polytechnic will select..." previously stored the sentence
            # as the provider name. A provider is a noun phrase, and a noun
            # phrase does not contain a full stop followed by a new sentence.
            r"(?:offered|provided|administered|funded|sponsored)\s+by\s+([A-Z][\w\s&'-]{3,70})",
            r"(?:ministry|department|agency|commission|council|foundation|university|institute|authority|embassy|organization|organisation|association)\s+(?:of|for)\s+([A-Z][\w\s&.,'-]{2,60})",
            r"(?:ministry|department|agency|commission|council|foundation|university|institute)\s+(?:of|for)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,5})",
            r"\bby\s+(?:the\s+)?([A-Z][A-Za-z&.'-]*(?:\s+(?:of|for|and)\s+|\s+)?(?:[A-Z][A-Za-z&.'-]*\s*){1,6})",
        ]
        for p in patterns:
            for m in re.finditer(p, text or "", re.MULTILINE):
                candidate = _truncate_at_sentence(" ".join(m.group(1).split()))
                # Reject fragments that are clearly not an organisation name.
                if len(candidate) < 4 or len(candidate) > 90:
                    continue
                if candidate.casefold() in _GENERIC_PROVIDER_REJECTS:
                    continue
                return candidate

        # "Japanese Government Scholarship" style: organisation adjective in
        # the page title, before the opportunity noun.
        if page_title:
            head = page_title.split(" | ")[0].split(" - ")[0].strip()
            for p in (
                r"^([A-Z][A-Za-z\s]{2,40}?)\s+(?:Scholarship|Grant|Fellowship|Programme|Program)",
                r"^([A-Z][A-Za-z\s]{2,40}?)\s+(?:Ministry|Department|Agency|Foundation|Commission)",
            ):
                m = re.match(p, head)
                if not m:
                    continue
                candidate = _truncate_at_sentence(" ".join(m.group(1).split()))
                # The title path gets the same rejection set as the body
                # patterns. Without it, a page titled "Other Scholarships and
                # Tuition Fee Reductions Systems" contributed a provider
                # literally called "Other".
                if len(candidate) < 4 or candidate.casefold() in _GENERIC_PROVIDER_REJECTS:
                    continue
                return candidate
        return None

    def _extract_scholarship_type(self, text: str) -> str | None:
        """Detect scholarship type (Government, University, etc.)"""
        types = ["government", "university", "foundation", "ngo", "company"]
        lowered = text.lower()
        for t in types:
            if t in lowered:
                return t.title()
        return None

    def _extract_degree(self, text: str) -> str | None:
        """Detect degree level from text.

        Returns a canonical value from the shared vocabulary, or None when the
        page does not state one Polaris supports.

        Previously this matched a private list that included "Doctorate", which
        the ingestion validator then rejected — a round trip that could never
        succeed. Normalising through the canonical vocabulary fixes that by
        construction: "Doctorate" is an alias of "PhD", and anything else is
        simply not a degree level Polaris recognises.

        It returns None rather than guessing, in three distinct cases, and
        the distinction matters because each one is a different failure:

        * the page states a qualification with no degree level (a polytechnic
          diploma, a foundation programme). Mapping it to Bachelor would
          assert the student already holds a degree they do not have
          (ADR-016), so the wording is recorded as evidence instead;
        * the page states *several* levels, which is what an eligibility list
          looks like. "An existing Master's degree ... a UK Doctoral
          qualification" is a list of what applicants may hold, not a
          statement of what the award is. The candidates are recorded so a
          reviewer can settle it against the page;
        * the page states none of them, in which case there is nothing to
          record.
        """
        from services.domain.vocabulary import qualifies_as_unmapped_qualification

        # Reset before reading, not after writing. The attribute is set only
        # on the unmapped path, so a client reused across pages (which is how
        # acquisition runs it) carried the previous page's evidence into the
        # next extraction. A record then claimed its source said "diploma"
        # when that word appeared on a different page entirely.
        self.last_unmapped_qualification = None
        self.last_degree_candidates = []

        lowered = text.lower()
        levels = _declared_degree_levels(lowered)

        if len(levels) == 1:
            return next(iter(levels))
        if len(levels) > 1:
            # Ambiguous. A confidence value must not silently pick a side:
            # the record becomes reviewable instead of confidently wrong.
            self.last_degree_candidates = sorted(levels)
            return None

        # A qualification Polaris will not map. Recorded as evidence so the
        # reviewer sees the source wording instead of a silent null.
        unmapped = qualifies_as_unmapped_qualification(lowered)
        if unmapped:
            self.last_unmapped_qualification = unmapped
        return None

    @staticmethod
    def _unmapped_funding_statement(text: str) -> str | None:
        """Cost-coverage wording the funding vocabulary cannot represent.

        "All tuition fees, travel and living costs" is not one of the three
        canonical values and is not a completeness claim like "fully funded"
        (ADR-018). The ladder answers *how much of the cost base is covered*;
        this sentence enumerates three lines and is silent about the rest.

        Recording it is what keeps a NULL ``funding_type`` legible. Without it
        the reviewer's screen shows an empty field and no way to tell a page
        that said nothing from a page that said something the pipeline could
        not classify. The wording is preserved; the value stays NULL.

        The statement must also sit in a funding context. In this corpus 24 of
        the 25 pages containing such a phrase are describing money the student
        raises themselves — "Lendwise Student Loan ... can cover tuition fees
        and living expenses", "a letter confirming that all tuition fees will
        be paid by the sponsor". Sending a reviewer to those sentences would
        point them at the wrong evidence entirely, so the phrase only counts
        when something nearby is talking about the award's funding.
        """
        best: str | None = None
        for pattern in _UNMAPPED_FUNDING_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                before = text[max(0, match.start() - 60) : match.start()]
                if not re.search(_FUNDING_EVIDENCE_CONTEXT_NOUN, before, re.IGNORECASE):
                    continue
                if best is None or len(match.group(0)) > len(best):
                    best = " ".join(match.group(0).split())
                break
        return best

    @staticmethod
    def _source_terms(text: str) -> dict[str, str]:
        """Source wording for controlled fields whose text differs from the value.

        A field is only worth recording when the page said something other
        than the canonical term — "postgraduate" and "Master" are the same fact
        written differently, and the original phrasing is what lets a reviewer
        confirm the normalization was correct.
        """
        lowered = text.lower()
        terms: dict[str, str] = {}
        for label, vocabulary in (("degree", DEGREE), ("funding_type", FUNDING_TYPE)):
            match = _longest_alias_match(
                lowered,
                vocabulary,
                context_noun=_DEGREE_CONTEXT_NOUN if vocabulary is DEGREE else _FUNDING_CONTEXT_NOUN,
            )
            if not match:
                continue
            alias, canonical = match
            if canonical.lower() == alias.lower():
                continue  # canonical spelling, nothing was normalized
            terms[label] = alias
        return terms

    def _extract_funding_type(self, text: str) -> str | None:
        """Detect funding type, mapping to the canonical vocabulary."""
        match = _longest_alias_match(text.lower(), FUNDING_TYPE, context_noun=_FUNDING_CONTEXT_NOUN)
        # Retained so `_funding_evidence` can quote the sentence the verdict
        # rests on. A funding claim with no quotable source is exactly what
        # V0.1 published 18 times ("Fully Funded", `source_value = NULL`).
        self._funding_match = match
        return match[1] if match else None

    def _funding_evidence(self, text: str, funding_type: str | None) -> dict | None:
        """The wording that produced a funding classification, or None.

        Returns ``{"alias", "canonical", "statement"}``. A reviewer reading a
        published funding claim needs to see the sentence it came from without
        re-opening the source document; ``statement`` is that sentence, trimmed.
        """
        match = getattr(self, "_funding_match", None)
        if not funding_type or not match:
            return None
        alias = match[0]
        lowered = text.lower()
        # Re-find the alias in the original text to slice the sentence, which
        # keeps the page's own capitalisation and wording.
        hit = next(_word_bounded(lowered, alias), None)
        if hit is None:
            return None
        start = max(hit.start() - 160, 0)
        end = min(hit.end() + 160, len(text))
        statement = " ".join(text[start:end].split())
        return {
            "alias": alias,
            "canonical": funding_type,
            "statement": statement,
        }

    def _extract_country_heuristic(self, text: str) -> str | None:
        """Heuristic extraction of country from text using known ISO2 mappings.

        Returns an ISO2 code or None if nothing matches.
        """
        # Order matters: more specific patterns first
        patterns = [
            (r"Japan|日本", "JP"),
            (r"China|中国|中华人民共和国", "CN"),
            (r"Republic of Korea|South Korea|대한민국|韓国|韓国", "KR"),
            (r"Germany|Deutschland", "DE"),
            (r"France|République française", "FR"),
            (r"United Kingdom|Britain", "GB"),
            (r"United States|USA|America", "US"),
            (r"Australia", "AU"),
            (r"Indonesia", "ID"),
            (r"Russia|Russian Federation", "RU"),
            (r"Netherlands|The Netherlands|Dutch", "NL"),
            (r"Qatar", "QA"),
            (r"Saudi Arabia", "SA"),
            (r"Türkiye|Turkey", "TR"),
            (r"Canada", "CA"),
            (r"Italy", "IT"),
            (r"Spain", "ES"),
            (r"Sweden", "SE"),
            (r"Switzerland", "CH"),
            (r"Norway", "NO"),
            (r"Denmark", "DK"),
            (r"Finland", "FI"),
            (r"Belgium", "BE"),
            (r"Ireland", "IE"),
            (r"Austria", "AT"),
            (r"Poland", "PL"),
            (r"Malaysia", "MY"),
            (r"Singapore", "SG"),
            (r"New Zealand", "NZ"),
            (r"South Africa", "ZA"),
            (r"United Arab Emirates|UAE", "AE"),
        ]
        for pattern, code in patterns:
            if re.search(pattern, text):
                return code
        return None

    def _extract_fields_of_study(self, text: str) -> list[str]:
        """Heuristic extraction of fields of study from text.

        Returns an empty list if no specific fields are mentioned. The list
        is intentionally permissive so validation passes; specific filtering
        happens downstream.
        """
        fields = [
            "Engineering",
            "Computer Science",
            "Natural Sciences",
            "Mathematics",
            "Medicine",
            "Law",
            "Business",
            "Economics",
            "Humanities",
            "Social Sciences",
            "Arts",
            "Education",
            "Agriculture",
            "Architecture",
        ]
        lowered = text.lower()
        matched: list[str] = []
        for f in fields:
            if f.lower() in lowered:
                matched.append(f)
        # "All fields of study" is a claim the page has to actually make. Testing
        # for "all" and "field" anywhere in the text accepted it for any page
        # containing the phrase "every field", which asserts a fact about the
        # scholarship's scope that the source never made.
        if not matched and re.search(r"\ball\s+(?:of\s+)?(?:the\s+)?field", lowered):
            matched.append("All Fields")
        return matched

    def extract_scholarship(
        self,
        clean_text: str,
        source_url: str,
        default_country: str | None = None,
        page_title: str = "",
        headings: tuple = (),
        anchors: tuple = (),
        looks_like_index: bool = False,
        default_country_confidence: float = 0.3,
        anchor_links: tuple = (),
    ) -> Dict[str, Any]:
        if default_country is None:
            default_country = self.default_country
        verdict = self._extract_name_verdict(clean_text, page_title, headings, anchors, looks_like_index)
        # No placeholder name. "Unknown Scholarship" reaching the Knowledge Base
        # is what M8 produced; a None name is honest and routes the record to
        # review where a human can read the page themselves.
        name = verdict.normalized_name if verdict.accepted else None

        # A page with open-ended application semantics has no fixed deadline;
        # any date the patterns latch onto there is decoration, not a deadline.
        from services.scholarship.freshness import detect_rolling

        if detect_rolling(clean_text):
            deadline, deadline_conflict = None, None
        else:
            deadline, deadline_conflict = self._resolve_deadline(clean_text)
        cycle = self._extract_cycle(clean_text)
        gpa = self._extract_gpa(clean_text)
        age = self._extract_age_limit(clean_text)
        toefl_required, toefl_score = self._extract_toefl(clean_text)
        benefits = self._extract_benefits(clean_text)

        # Heuristic extraction for missing fields
        # Provider, type, degree, funding and country are resolved from the
        # page when it states them. The fallback country is an assumption
        # (the source's country), so it is reported as low confidence rather
        # than presented as extracted fact.
        #
        # M10: an unresolved provider stays None. "Unknown" was a sentinel in
        # the same family as the M8 "Unknown Scholarship": it survived into
        # the Provider table as if it were an organisation's name. None says
        # "this page did not name it", and the mapper falls back to the
        # SourceRegistry row that produced this document.
        provider_name = self._extract_provider_name(clean_text, page_title)
        scholarship_type = self._extract_scholarship_type(clean_text)  # None if unknown
        degree = self._extract_degree(clean_text)  # None if unknown
        # Several levels stated under a level label is the award's own set,
        # not an applicant requirement list; the module explains the line.
        degree_levels = (
            [] if degree else declared_award_levels(clean_text)
        )
        funding_type = self._extract_funding_type(clean_text)  # None if unknown
        country_from_page = self._extract_country_heuristic(clean_text)
        country = country_from_page or default_country
        country_inferred = country_from_page is None
        field_of_study = self._extract_fields_of_study(clean_text)
        official_source, application_url = self._select_link_targets(source_url, anchor_links)

        return {
            "scholarship_name": name,
            "provider_name": provider_name,
            "scholarship_type": scholarship_type,
            "country": country,
            "university": None,
            "degree": degree,
            "degree_levels": degree_levels,
            "funding_type": funding_type,
            "field_of_study": field_of_study,
            "application_url": application_url,
            "official_source": official_source,
            "timeline": {
                "application_open": None,
                "application_deadline": deadline,
                "application_cycle": cycle,
                "interview_date": None,
                "result_date": None,
                "study_start": None,
            },
            "eligibility": {
                "minimum_gpa": gpa,
                "ielts_required": None,
                "minimum_ielts": None,
                "toefl_required": toefl_required if toefl_score else None,
                "minimum_toefl": toefl_score,
                "gre_required": None,
                "age_limit": age,
                "work_experience": None,
                "research_experience": self._extract_research_experience(clean_text),
                "publication": None,
                "recommendation_letter": bool(re.search(r"recommendation", clean_text, re.IGNORECASE)),
                "motivation_letter": None,
                "cv_required": None,
                "passport_required": None,
            },
            "benefits": benefits,
            # --- M9 extraction provenance / confidence ---
            "_extraction": {
                "name_verdict": {
                    "accepted": verdict.accepted,
                    "confidence": verdict.confidence,
                    "reasons": verdict.reasons,
                    "normalized_name": verdict.normalized_name,
                },
                # Recorded so the mapper can store per-field provenance and the
                # reviewer can see when the value was read, not just from where.
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "method": "deterministic_extractor",
                "country_inferred_from_source": country_inferred,
                "country_confidence": default_country_confidence if country_inferred else 0.8,
                "source_url": source_url,
                "page_title": page_title,
                "outbound_links": self._serialize_anchor_links(source_url, anchor_links),
                # Source wording that normalization changed, and any
                # qualification the domain has no category for. Evidence for
                # the reviewer, never a value (ADR-016, Phase 9).
                "source_terms": self._source_terms(clean_text),
                "deadline_conflict": deadline_conflict,
                "unmapped_funding_statement": (None if funding_type else self._unmapped_funding_statement(clean_text)),
                # Why this funding verdict, in the page's own words. None when
                # there is no classification to justify.
                "funding_evidence": self._funding_evidence(clean_text, funding_type),
                "unmapped_qualification": self.last_unmapped_qualification,
                # Present only when the page declared more than one level.
                "degree_candidates": self.last_degree_candidates or None,
            },
        }

    @staticmethod
    def _serialize_anchor_links(source_url: str, anchor_links: tuple) -> list[dict[str, str]]:
        """Keep visible external links available for later official verification."""
        source_domain = registered_domain(domain_of(source_url))
        links: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in anchor_links or ():
            if isinstance(item, dict):
                label, href = str(item.get("text", "")), str(item.get("href", ""))
            else:
                label = str(getattr(item, "text", ""))
                href = str(getattr(item, "href", ""))
            absolute = urldefrag(urljoin(source_url, href.strip()))[0]
            parts = urlsplit(absolute)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                continue
            target_domain = registered_domain(domain_of(absolute))
            if target_domain == source_domain or absolute in seen:
                continue
            seen.add(absolute)
            links.append({"text": " ".join(label.split())[:200], "url": absolute[:2048]})
            if len(links) >= 200:
                break
        return links

    @classmethod
    def _select_link_targets(cls, source_url: str, anchor_links: tuple) -> tuple[str | None, str | None]:
        """Choose URLs only from explicitly labelled external links.

        A missing label or destination stays unknown. The aggregator article
        URL is never used as a substitute for either target.
        """
        official_label = re.compile(
            r"\b(?:official(?:\s+(?:scholarship|program(?:me)?))?\s+(?:website|site|source|page|portal|link)|visit\s+official)\b",
            re.I,
        )
        application_label = re.compile(
            r"\b(?:apply(?:\s+(?:now|here))?|application\s+(?:form|portal|page|website)|"
            r"submit\s+(?:your\s+)?application|start\s+application)\b",
            re.I,
        )
        serialized = cls._serialize_anchor_links(source_url, anchor_links)
        from services.exploration.url_utils import registered_domain

        internal_hosts = {"fullyscholarships.com", "opportunitiescircle.com"}

        def host(url: str) -> str:
            return registered_domain(urlsplit(url).hostname or "")

        article_host = host(source_url)
        external = [
            item for item in serialized
            if host(item["url"]) != article_host
        ]
        official_item = next(
            (item for item in external if official_label.search(item["text"])), None
        )
        application_item = next(
            (item for item in external if application_label.search(item["text"])), None
        )

        # Aggregator posts often label the provider link with its name instead
        # of "Official Site". Limit the fallback to configured aggregators and
        # identifiable labels. The official-source verifier still checks the
        # destination before persistence.
        if official_item is None and article_host in internal_hosts:
            neutral_labels = {"click here", "read more", "learn more", "website", "visit website"}
            official_item = next(
                (
                    item for item in external
                    if item is not application_item
                    and item["text"].strip().casefold() not in neutral_labels
                    and not application_label.search(item["text"])
                ),
                None,
            )

        official = official_item["url"] if official_item else None
        application = application_item["url"] if application_item else None
        return official, application
