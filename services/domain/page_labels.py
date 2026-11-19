"""Labels that name a page section, not a scholarship programme.

"JSPS Topics", "2027-2028 Fellowship Categories", "Fees and funding" and
"3. Interview" are the page's own table of contents. They mention funding, so
a keyword-based extractor can turn them into a scholarship record; a reader
cannot apply to any of them.

The rule is structural, not a list of strings found in one run:

* a numbered heading (``3. Interview``) is a step, not an award;
* a title that is only a section noun or a short noun phrase headed by one
  (``Topics``, ``Fellowship Categories``, ``Guidelines on tuition fees``) is a
  section;
* a page whose title starts with ``About`` / ``Contact`` and runs longer than
  a name is an organisation page;
* the phrases below describe process (fees, how to apply, selection) rather
  than the thing being awarded.

It is shared by the discovery classifier (which page may be extracted) and the
extraction quality gate (which string may become a name), so the two cannot
disagree about what a section label is.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")
_SITE_SUFFIX = re.compile(r"\s*(?:\||｜|::|·)\s*|\s+[-–—]\s+")
_NUMBERED_HEADING = re.compile(r"^\d{1,2}[.)]\s+\S")
_ABOUT_PAGE = re.compile(r"^(?:about|contact)\b", re.I)

#: Whole-string labels. Compared after site-suffix stripping and case folding.
_EXACT = frozenset(
    {
        "topics",
        "news",
        "categories",
        "category",
        "fees and funding",
        "tuition fees",
        "guidelines",
        "overview",
        "important dates",
        "application process",
        "application procedure",
        "how to apply",
        "requirements",
        "eligibility",
        "interview",
        "selection process",
        "faq",
        "archive",
        "program guidelines",
        "programme guidelines",
        "scholarship categories",
        "fellowship categories",
        "types of scholarships",
        "about us",
        "contact us",
    }
)

#: Last-word nouns that name a part of a page. A short phrase ending in one of
#: these describes the page, not an award. Funding nouns are deliberately
#: absent: "Chevening Scholarships" ends in one and is a real programme.
_HEAD_NOUNS = frozenset(
    {
        "topics",
        "topic",
        "categories",
        "category",
        "guidelines",
        "guideline",
        "fees",
        "fee",
        "funding",
        "process",
        "procedure",
        "procedures",
        "methods",
        "method",
        "requirements",
        "requirement",
        "eligibility",
        "interview",
        "overview",
        "information",
        "news",
        "archive",
        "registrants",
        "dates",
    }
)

#: Phrases that describe process or cost rather than one award.
_PHRASES = (
    "fees and funding",
    "tuition fee",
    "tuition fees",
    "how to apply",
    "application process",
    "application procedure",
    "application method",
    "selection process",
    "program guidelines",
    "programme guidelines",
    "important dates",
    "academic year",
    "scholarship categories",
    "fellowship categories",
    "scholarships offered",
    "scholarships for",
    "scholarships by",
    "scholarship opportunities",
    "funding opportunities",
)


def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", (text or "").strip()).strip(" .:;,-–—")


def section_label(text: str) -> str | None:
    """The section label ``text`` is, or None when it reads as a name.

    Returning the matched label (rather than a boolean) lets callers record
    *what* they objected to, which is the difference between a review queue
    that can be audited and one that says "rejected".
    """
    value = _clean(text)
    if not value:
        return None

    # "Topics | JSPS" — judge the page's own label, not the publisher suffix.
    head = _SITE_SUFFIX.split(value)[0].strip()
    lowered = head.casefold()

    if _NUMBERED_HEADING.match(head):
        return head
    if _ABOUT_PAGE.match(head) and len(head.split()) > 2:
        return head
    if lowered in _EXACT:
        return head

    for phrase in _PHRASES:
        if phrase in lowered:
            return head

    words = re.findall(r"[a-z0-9]+", lowered)
    if words and len(words) <= 5 and words[-1] in _HEAD_NOUNS:
        return head
    return None
