"""Extraction quality — deciding whether a candidate name is a real
scholarship identity or a scrap of portal chrome.

The M8 heuristic extractor produced names like ``Unknown Scholarship``,
``Number of Scholarship``, ``Das Program`` and ``At a glance Grant``. Those
are not bad regexes; they are the *wrong question*. A regex either matches
something shaped like a name or it does not, and portal pages are full of
text shaped like names.

This module answers a different question: given a candidate string and the
page it came from, how strongly does the evidence support treating this as
the identity of one scholarship?

    candidate string
        ↓ genericity      — is this just a funding noun / UI label?
        ↓ page context    — does the page present it as a heading/anchor?
        ↓ identity shape  — does it name a specific programme?
        ↓
    ExtractionVerdict(accepted, confidence, reasons, normalized_name)

Design rules, in priority order:

1. **No blacklist.** Every rejected string is rejected by a *reason*
   (genericity, no-identity-token, context-mismatch), not by membership in
   a list of known-bad strings. A list of bad strings grows forever and
   still misses the next one; reasons generalize.
2. **Reject to PENDING_REVIEW, never to approval.** A low verdict means
   the extractor does not know, and the reviewer decides. It never means
   "publish it anyway" and never means "silently drop it".
3. **Multilingual.** Government portals are not English. Signals are
   structural (headings, anchors, script boundaries) rather than an English
   word list.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from services.domain.page_labels import section_label

# Verdict threshold. Above this the extractor is confident enough to skip
# the "identity is obviously wrong" gate; it still does NOT auto-approve,
# because publication is a human decision (M9 principle 3).
CONFIDENCE_ACCEPT = 0.55

# Funding/opportunity nouns across the languages Polaris actually meets in
# practice. Used only to judge whether a candidate string *is just a noun* —
# never to build a reject list. A name may legitimately contain one of these
# ("DAAD Development-Related Postgraduate Courses"); what disqualifies it is
# having nothing else.
_FUNDING_NOUNS = {
    # English
    "scholarship", "scholarships", "scholar", "scholars", "fellowship",
    "grant", "grants", "bursary", "stipend", "award", "awards", "funding",
    "financial aid", "programme", "program", "course", "studentship",
    "tuition", "money", "opportunity", "opportunities",
    # Japanese
    "奨学金", "奨学生", "留学",
    # Korean
    "장학금", "장학",
    # Chinese
    "奖学金", "助学金",
    # Indonesian / Malay
    "beasiswa", "biasiswa",
    # French / German / Spanish
    "bourse", "stipendium", "becas", "stipendio",
}

# UI labels and section chrome. Same caveat: these disqualify a candidate
# only when they are effectively the *whole* string, never as substrings of
# a real name.
_UI_LABELS = {
    "at a glance", "read more", "learn more", "apply now", "view details",
    "click here", "more information", "home", "back to top", "menu",
    "contact us", "about us", "search", "news", "events", "faq",
    "skip to main content", "how to apply", "important dates", "overview",
    "introduction", "eligibility", "benefits", "application", "documents",
    "important notice", "notice", "top", "next", "previous", "close",
}

# Indefinite articles. A scholarship name is a bare noun phrase; an
# indefinite article means the string is a *description* ("ein besonderes
# Program" = "a special programme"), not the name of one thing.
#
# Definite articles are deliberately absent: they legitimately occur inside
# proper names ("The Rhodes Scholarship"), so only indefinite ones disqualify.
_INDEFINITE_DETERMINERS = {
    "a", "an", "ein", "eine", "einen", "einem", "einer", "eines",
    "suatu", "sebuah",
}

# Pronouns and instruction verbs. Closed-class vocabulary, not a reject
# list: these words make a string *prose*, whereas a scholarship name is a
# noun phrase. This is what separates the German portal sentence
# "Bitte entnehmen Sie der Program" from the title "Helmut-Schmidt-Programme"
# without knowing either string in advance.
_PROSE_MARKERS = {
    # English pronouns / instruction verbs
    "please", "kindly", "apply", "visit", "click", "see", "refer", "check",
    "submit", "complete", "download", "read", "find", "contact", "email",
    "register", "sign", "login", "note", "be", "is", "are", "was", "were",
    "you", "your", "we", "our", "us", "they", "their", "them", "he", "she",
    "his", "her", "i", "me", "my", "who", "what", "which", "when", "where",
    # German pronouns / instruction verbs
    "bitte", "sie", "ihr", "er", "es", "wir", "ihre", "unser", "entnehmen",
    "beantragen", "bewerben", "anmelden", "klicken", "lesen", "hier", "diese",
    "dieser", "dieses", "werden", "wird", "ist", "sind", "kontakt",
    # Indonesian / Malay pronouns / instruction verbs
    "silakan", "klik", "lihat", "bacalah", "hubungi", "daftar", "yang",
}

# Phrases that introduce page chrome. Stripped from the front of a candidate
# before judging what remains, so "At a glance Grant" is judged as "Grant"
# (names nothing) rather than as a title-cased name.
_UI_PREFIXES = (
    "at a glance", "how to apply", "how to", "read more", "learn more",
    "more information", "important notice", "important dates", "please note",
    "for more", "see also", "quick facts", "key facts", "overview",
)

_WHITESPACE = re.compile(r"\s+")
_WORD_SPLIT = re.compile(r"[\s/|·:;,()\[\]]+")

# Structural identity patterns: unambiguous evidence that a string names a
# specific programme rather than a category.
_IDENTITY_TOKEN_PATTERNS = [
    re.compile(r"\b(19|20)\d{2}\b"),                       # year / cohort
    re.compile(r"\b20\d{2}[-/]\d{2,4}\b"),                # academic year span
    re.compile(r"\b[A-Z]{2,}(?:-[A-Z]{2,})*\b"),           # acronyms: MEXT, DAAD, JASSO
    re.compile(r"['’][A-Za-z]{2,}"),                      # O'Keeffe, students'
    re.compile(r"[一-鿿぀-ヿ가-힯]{2,}"),                  # CJK/Hangul runs
    re.compile(r"\d"),                                    # numbered programme
]

# Every identity token *except* the non-Latin run.
#
# A CJK/Hangul run proves the string is written in a real script, which is
# good evidence that something is named — but site navigation is written in
# real scripts too ("ヘッダー プライマリーリンク（英語）" is a header link
# label). So a non-Latin run cannot by itself establish that a candidate is
# about a scholarship; see `_names_an_opportunity`.
_NON_LATIN_RUN = re.compile(r"[一-鿿぀-ヿ가-힯]{2,}")
_LATIN_IDENTITY_PATTERNS = [
    p for p in _IDENTITY_TOKEN_PATTERNS if p.pattern != _NON_LATIN_RUN.pattern
]

# Prose signals that work without spaces.
#
# `_looks_like_prose` counts words, and Japanese and Chinese write without
# them, so a complete sentence comes through as one "word" and passes every
# length and marker test. A real observed case: the AFS scholarship page's
# heading "AFSでの留学には、様々な奨学金がご利用いただけます。" — a sentence
# ending in a full stop — was accepted as a scholarship name at 0.70.
_CJK_SENTENCE_MARKERS = re.compile(r"[。．！？!?]|です|ます|ください|します|した。")


def _reads_as_unspaced_prose(text: str) -> bool:
    """Whether a non-Latin candidate is a sentence rather than a name."""
    return bool(_CJK_SENTENCE_MARKERS.search(text))

# Words that add nothing: quantifiers and function words. "Number of
# Scholarship" and "Amount of Scholarship" are exactly a quantifier, a
# function word and a funding noun.
_QUANTIFIERS = {
    "number", "amount", "list", "lists", "amounts", "type", "types",
    "kind", "kinds", "form", "forms", "name", "names", "title", "titles",
    "all", "some", "any", "each", "every", "one", "two", "new", "top",
    "best", "latest", "current", "full", "complete", "list",
    # Indefinite quantifiers. "Other Scholarship Opportunities" is the same
    # failure as "Number of Scholarship" — a quantifier in front of a funding
    # noun, naming a category rather than a programme.
    "other", "others", "various", "several", "certain", "additional", "further",
}

_FUNCTION_WORDS = {
    "of", "for", "and", "or", "the", "a", "an", "in", "at", "on", "to",
    "with", "by", "from", "as", "that", "this", "these", "those", "is",
    "are", "was", "were", "be", "we", "you", "it", "its",
    # German / Indonesian function words that surface as a leading capital
    # and would otherwise read as a proper noun.
    "das", "der", "die", "dem", "den", "ein", "eine", "und", "oder",
    "yang", "dan", "untuk", "dengan", "adalah", "einen", "einem", "zum", "zur",
}

# Funding descriptors. Domain vocabulary describing *how* money is given,
# not which programme. "Fully Funded Scholarship" names no programme, even
# though every word is a real English word.
_FUNDING_DESCRIPTORS = {
    "fully", "fully funded", "funded", "partial", "partially", "partly",
    "tuition only", "bond-free", "bond free", "need-based", "need based",
    "merit-based", "merit based", "means-tested", "means tested",
    "full ride", "full tuition", "stipend", "allowance", "coverage",
    "visit", "welcome",
}

# Listing-page adjectives that describe availability, not identity.
_LISTING_ADJECTIVES = {
    "available", "upcoming", "current", "ongoing", "open", "closed",
    "eligible", "listed", "featured", "popular", "new", "all",
}

# Multi-word funding phrases counted as a single generic noun.
_FUNDING_PHRASES = {
    "financial aid", "student funding", "tuition waiver", "study grant",
    "postgraduate research", "doctoral research", "summer programme",
    "summer program", "short course", "student loan",
}

# Words that describe a *document* rather than an opportunity.
#
# Same closed-class logic as `_PROSE_MARKERS` and `_UI_LABELS`: these are the
# nouns a page uses to name its own sections and overlays, so a candidate built
# only from them describes where you are on a site, not what you could apply
# for. This is a class of concepts, not a list of strings found to be wrong --
# "Application procedure & deadlines", "Cookie Consent" and "Frequently Asked
# Questions" are rejected for the same reason, and so would be "Selection
# process" or "Award quantum" on a site this milestone never saw.
_DOCUMENT_FACET_NOUNS = {
    # English
    "question", "questions", "faq", "faqs", "procedure", "procedures",
    "deadline", "deadlines", "information", "overview", "description",
    "benefit", "benefits", "requirement", "requirements", "criteria",
    "eligibility", "applicant", "applicants", "application", "applications",
    "consent", "cookie", "cookies", "policy", "policies", "contact",
    "inquiries", "inquiry", "enquiry", "news", "events", "update", "updates",
    "notice", "notices", "bulletin", "newsletter", "newsletters", "glossary",
    "faq's", "contents", "navigation", "menu", "search", "share", "quick",
    # Japanese
    "お問い合わせ", "/faq", "採用", "募集要項",
}

# Trailing words that describe the page's *kind* rather than the opportunity.
# Judged against the trimmed string and published untrimmed, so
# "DAAD Scholarships - An Overview" keeps its name while the page-type word
# stops disqualifying it.
_UI_SUFFIXES = (
    "overview", "faqs", "faq", "index", "list", "page", "section", "home",
)

# Separators a site name is appended to a page title with. Titles arrive as
# "PFP Study Award | Temasek Polytechnic" or "DAAD Scholarships - An Overview
# - DAAD"; the site name is the publisher, never the scholarship.
_TITLE_SITE_SEPARATORS = ("|", "｜", " - ", " – ", " :: ", " · ")


def _strip_punctuation_edges(text: str) -> str:
    """Trim decorative punctuation without destroying balanced brackets.

    A trailing ``)`` is chrome in "Eiffel Scholarship )" but part of the
    name in "DAAD ... Courses (EPOS)". Only unbalanced edges are removed.
    """
    text = (text or "").strip()
    text = text.strip(" \t\r\n-–—|·:;,.\"'*#")
    openers = {")": "(", "]": "[", "}": "{"}
    closers = {"(": ")", "[": "]", "{": "}"}
    while text and text[-1] in openers and text.count(text[-1]) > text.count(openers[text[-1]]):
        text = text[:-1].rstrip()
    while text and text[0] in closers and text.count(text[0]) > text.count(closers[text[0]]):
        text = text[1:].lstrip()
    return text.strip(" \t\r\n-–—|·:;,.\"'*#")


def _leading_segment(text: str) -> str:
    """The part of a title before the first site-name separator."""
    trimmed = _collapse(text)
    positions = [trimmed.find(sep) for sep in _TITLE_SITE_SEPARATORS]
    positions = [p for p in positions if p > 0]
    if not positions:
        return text
    return trimmed[: min(positions)].strip(" .:-–—|")


def strip_site_suffix(text: str) -> str:
    """Drop the site name a page title appends after a separator.

    Applied to the published name as well as to the judgement, because the
    site name is a fact about the publisher and never a fact about the
    scholarship: "PFP Study Award | Temasek Polytechnic" names the award once.

    Three guards, each earning its place on a real page:

    * the tail must be short — a publisher name is a name, not a clause;
    * the tail must not contain a funding noun — "Engineering Scholarship" in
      a title is part of the award's name, not the site that published it;
    * the tail must not end in a page-type word — that is "DAAD Scholarships -
      An Overview", where "An Overview" describes the document.

    Only the *last* segment is dropped, and only when what remains still names
    something.
    """
    trimmed = _collapse(text)
    for separator in _TITLE_SITE_SEPARATORS:
        head, found, tail = trimmed.rpartition(separator)
        if not found or not head.strip():
            continue
        tail_words = tokenize_words(tail)
        if not tail_words or len(tail_words) > 5:
            continue
        if tail_words[-1] in _UI_SUFFIXES:
            continue
        if any(word in _FUNDING_NOUNS for word in tail_words):
            continue
        remainder = head.strip(" .:-–—|｜·")
        # Keep the head when it is still a plausible name on its own; a title
        # that is only a site name ("KYOTO UNIVERSITY") has no head to keep.
        if len(remainder) >= 6 and not _strip_punctuation_edges(remainder).isupper():
            return remainder
    return text


def _strip_ui_prefix(text: str) -> str:
    """Remove a leading page-chrome phrase, leaving the candidate's own words."""
    lowered = _collapse(text).casefold()
    for prefix in _UI_PREFIXES:
        if lowered.startswith(prefix + " "):
            remainder = _collapse(text)[len(prefix):].strip(" .:-–—")
            if remainder:
                return remainder
    return text


def _strip_ui_suffix(text: str) -> str:
    """Remove a trailing page-type word ("... - An Overview").

    The page-type word describes the document, not the opportunity, so it must
    not decide whether the name is publishable. The original string is still
    what gets published.
    """
    trimmed = _collapse(text)
    for suffix in _UI_SUFFIXES:
        if trimmed.casefold().endswith(" " + suffix):
            remainder = trimmed[: len(trimmed) - len(suffix) - 1].strip(" .:-–—|")
            # Removing "Overview" from "… - An Overview" would leave the
            # dangling article "An", which the prose test then reads as a
            # description. The determiner belonged to the page-type phrase.
            while (
                remainder.split()
                and remainder.split()[-1].casefold() in _INDEFINITE_DETERMINERS
            ):
                remainder = " ".join(remainder.split()[:-1]).strip(" .:-–—|")
            if remainder:
                return remainder
    return text


def _names_an_opportunity(text: str) -> bool:
    """Whether the candidate is about a scholarship/award at all.

    A name has to either contain a funding/opportunity noun or carry a
    structural identity token (a year, an acronym, a digit). The non-Latin
    script run is deliberately excluded from that second test: it proves the
    string is in a real script, but site navigation is too, and without this
    check a Japanese menu heading outscores the scholarship name on a Japanese
    university page.
    """
    lowered = _collapse(text).casefold()
    for word in tokenize_words(text):
        if word in _FUNDING_NOUNS:
            return True
        # Japanese and Chinese write without spaces, so "奨学金" sits inside a
        # run like "日本人大学院生奨学金" rather than being a token of its own.
        # Substring matching is safe here and only here: applied to Latin text
        # it would accept "Awarded students must…" because "award" is a
        # substring of "awarded".
        if not word.isascii() and any(noun in word for noun in _FUNDING_NOUNS):
            return True
    if any(phrase in lowered for phrase in _FUNDING_PHRASES):
        return True
    return any(p.search(text) for p in _LATIN_IDENTITY_PATTERNS)


def _is_banner_heading(text: str) -> bool:
    """Whether the string is set in capitals the way a category label is.

    Typographic convention, not a word list: programme names are written in
    title or sentence case, while breadcrumb trails, section banners and
    category labels ("UNDERGRADUATE SCHOLARSHIPS", "IMPORTANT DATES") are set
    in full caps. A name in capitals is a label someone typed in capitals.
    """
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 6:
        return False
    # A name that carries real content is never entirely uppercase, so this
    # only fires on strings where every letter is a capital.
    return all(c.isupper() for c in letters)


def _names_a_document_section(text: str) -> bool:
    """Whether the string's head noun says it *describes* rather than names.

    "General Scholarship Information", "Scholarship Requirements" and "Contact
    Information" all end in a noun about the document. A programme name ends
    in the thing it is — "…Scholarships", "…Grant", "…Award", "…Fellowship".
    """
    words = tokenize_words(text)
    if not words:
        return False
    return words[-1] in _DOCUMENT_FACET_NOUNS


def _names_a_document_facet(text: str) -> bool:
    """Whether the candidate is built only from document/interface nouns."""
    words = tokenize_words(text)
    if not words:
        return False
    meaningful = [
        w
        for w in words
        if w not in _QUANTIFIERS
        and w not in _FUNCTION_WORDS
        and w not in _FUNDING_NOUNS
        and w not in _FUNDING_DESCRIPTORS
        and w not in _LISTING_ADJECTIVES
        and w not in _UI_LABELS
    ]
    return bool(meaningful) and all(w in _DOCUMENT_FACET_NOUNS for w in meaningful)


@dataclass
class ExtractionVerdict:
    """Result of judging one candidate scholarship name."""

    accepted: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)
    normalized_name: str | None = None

    def explain(self) -> str:
        return "; ".join(self.reasons) if self.reasons else "no objection"


def _collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", (text or "").strip())


def _looks_like_prose(text: str) -> bool:
    """Whether the candidate reads as a sentence rather than a name."""
    words = tokenize_words(text)
    if any(w in _PROSE_MARKERS for w in words):
        return True
    # An indefinite article turns a bare name into a description of a
    # category: "Promovierende ein besonderes Program" is a heading about
    # doctoral programmes, not the name of one.
    if any(w in _INDEFINITE_DETERMINERS for w in words):
        return True
    # A noun phrase naming one programme is short. Long strings are sentences
    # whose capitalisation happened to survive extraction — unless the string
    # has the canonical <ProperNoun> + <opportunity noun> shape, which is the
    # shape a real name takes however many words it runs to ("The Fulbright /
    # Kennedy Center Fellowship for Performing Arts And Science").
    return len(words) > 9 and not _has_canonical_name_shape(text)


def _has_canonical_name_shape(text: str) -> bool:
    """True for ``ProperNoun + OpportunityNoun`` — the canonical name shape.

    "Eiffel Scholarship", "Australia Awards", "Chevening Scholarships" all
    have this shape. It is the strongest structural evidence available when a
    name carries no year or acronym, and it is what distinguishes them from
    "Number of Scholarship", where the word before the noun is a quantifier.
    """
    tokens = [t for t in _WORD_SPLIT.split(_collapse(text)) if t]
    for index in range(1, len(tokens)):
        if tokens[index].strip(".,;:!?\"'()").casefold() not in _FUNDING_NOUNS:
            continue
        previous = tokens[index - 1].strip(".,;:!?\"'()")
        bare = previous.casefold()
        if not previous or not previous[0].isupper():
            return False
        if (
            bare in _FUNDING_NOUNS
            or bare in _FUNCTION_WORDS
            or bare in _QUANTIFIERS
            or bare in _FUNDING_DESCRIPTORS
            or bare in _LISTING_ADJECTIVES
        ):
            return False
        return True
    return False


def tokenize_words(text: str) -> list[str]:
    """Split into case-folded word tokens, keeping non-Latin runs intact."""
    return [t.casefold() for t in _WORD_SPLIT.split(text) if t]


def _is_ui_label(text: str) -> bool:
    return _collapse(text).casefold().rstrip(" .:") in _UI_LABELS


def substantive_words(text: str) -> list[str]:
    """Words that carry meaning: not a funding noun, quantifier, or function word."""
    lowered = _collapse(text).casefold()
    for phrase in _FUNDING_PHRASES:
        lowered = lowered.replace(phrase, " ")
    words = [w.strip(".,;:!?") for w in _WORD_SPLIT.split(lowered) if w.strip(".,;:!?")]
    return [
        w
        for w in words
        if w not in _FUNDING_NOUNS
        and w not in _UI_LABELS
        and w not in _QUANTIFIERS
        and w not in _FUNCTION_WORDS
        and w not in _FUNDING_DESCRIPTORS
        and w not in _LISTING_ADJECTIVES
    ]


def _is_all_funding_nouns(text: str) -> bool:
    """True when every meaningful word is a generic funding/opportunity noun.

    This is the general form of "Unknown Scholarship", "Number of
    Scholarship" and "Fully Funded Scholarship": the string names the
    *category* of opportunity and nothing else. No lookup table of bad
    strings is required — only "is there a word that names something".
    """
    return not substantive_words(text)


#: Phrases that describe a funding *policy* rather than a programme. A page
#: that says "tuition reduction and exemption system" is describing how an
#: institution handles fees, not naming an award a student applies to.
_GENERIC_POLICY_PHRASES = (
    "tuition reduction",
    "tuition waiver",
    "tuition exemption",
    "fee waiver",
    "fees waiver",
    "financial aid system",
    "scholarship system",
    "exemption system",
)

_GENERIC_LEADING_WORDS = {
    "international", "global", "national", "general", "other", "all", "new",
    "full", "partial", "available", "current", "postgraduate", "undergraduate",
    "student", "students", "tuition", "fee", "fees",
}

_POLICY_WORDS = {
    "tuition", "fee", "fees", "reduction", "waiver", "exemption", "system",
    "policy", "scheme", "financial", "aid", "support", "assistance",
}


def _names_a_generic_policy(text: str) -> bool:
    """Whether the candidate names a fee policy with no specific identity.

    "International student tuition reduction and exemption system" is a
    policy page. "AUA Tuition Reduction/Exemption System" is that university's
    scheme and carries an identity token; "Fulbright Tuition Waiver" carries a
    proper name. Only the generic case is refused.
    """
    lowered = _collapse(text).casefold()
    if not any(phrase in lowered for phrase in _GENERIC_POLICY_PHRASES):
        return False
    if re.search(r"(?:19|20)\d{2}", text):
        return False

    tokens = [t for t in _WORD_SPLIT.split(_collapse(text)) if t]
    if not tokens:
        return False

    first = tokens[0].strip(".,;:!?\"'()").casefold()
    if first and first[0].isalpha() and first not in _GENERIC_LEADING_WORDS:
        # "Fulbright Tuition Waiver" — the first word is the programme's name,
        # not a sentence-initial adjective.
        return False

    for token in tokens[1:]:
        bare = token.strip(".,;:!?\"'()")
        folded = bare.casefold()
        if not bare or folded in _POLICY_WORDS or folded in _FUNCTION_WORDS:
            continue
        if bare[0].isupper():
            return False
    return True


def name_genericities(text: str) -> list[str]:
    """Reasons this string cannot be a real programme name, ignoring context.

    Extracted so the extractor (:func:`score_candidate_name`) and the review
    gate (:func:`services.review.quality.assess_identity`) judge a string by
    exactly one rule. When those two drifted apart, a name the extractor had
    already rejected could still clear the publication gate.
    """
    name = _strip_punctuation_edges(_collapse(text or ""))
    judged = _strip_ui_suffix(_strip_ui_prefix(name))
    found: list[str] = []

    if not name:
        found.append("empty candidate")
        return found
    if len(name) < 6:
        found.append(f"too short to identify a programme ({len(name)} chars)")
    if name.casefold() == "unknown scholarship" or name.startswith("unknown "):
        found.append("explicit unknown placeholder")
    if _is_ui_label(name):
        found.append("navigation/UI label, not a scholarship name")
    section = section_label(name)
    if section:
        # "JSPS Topics", "2027-2028 Fellowship Categories", "Fees and funding",
        # "3. Interview": a section of a page, not something to apply to.
        found.append(f"section label, not a programme name ({section[:60]})")
    if _names_a_generic_policy(name):
        found.append("names a funding policy or system, not a specific programme")
    # A title that glues a UI label onto the site name — "Frequently Asked
    # Questions | Honjo International Scholarship Foundation" — is still a UI
    # label. The site-name strip cannot help here because the site name itself
    # contains a funding noun ("…Scholarship Foundation"), so the leading
    # segment is judged on its own.
    head = _leading_segment(name)
    if head is not name and (_is_ui_label(head) or _names_a_document_section(head)):
        found.append("page-type label followed by a site name, not a programme name")
    if _is_banner_heading(name):
        found.append("set in capitals as a category banner, not a programme name")
    if _names_a_document_facet(judged):
        found.append("describes a page section or interface element, not a programme")
    if _reads_as_unspaced_prose(name):
        found.append("reads as a sentence, not a programme name")
    if _names_a_document_section(judged):
        found.append("describes a page section or interface element, not a programme")
    if _looks_like_prose(judged):
        found.append("reads as a sentence, not a programme name")
    if _is_all_funding_nouns(judged):
        found.append("names only the opportunity category, no specific programme")
    return found


def has_identity_tokens(text: str) -> tuple[bool, list[str]]:
    """Whether the string carries evidence of naming a *specific* programme.

    Two kinds of evidence, both structural rather than lexical:

    1. An unambiguous token — a year, an acronym, a non-Latin script run.
    2. A capitalised word that is not a generic funding noun. "Chevening
       Scholarships" names a programme because *Chevening* is a proper noun;
       "Fully Funded Scholarships" does not, because no word is proper.
    """
    hits = [p.pattern for p in _IDENTITY_TOKEN_PATTERNS if p.search(text)]
    if hits:
        return True, hits

    # Proper-noun test. Capitalisation only proves identity when it appears
    # somewhere other than the first word: English and German title-case
    # capitalise every content word, so a leading capital alone ("Fully",
    # "Available", "Das") proves nothing. A leading capital earns partial
    # credit and must be corroborated by page context; a mid-string capital
    # is strong evidence on its own.
    tokens = [t for t in _WORD_SPLIT.split(_collapse(text)) if t]
    for index, token in enumerate(tokens):
        bare = token.strip(".,;:!?\"'()").casefold()
        if not bare or not bare[0].isalpha():
            continue
        if (
            bare in _FUNDING_NOUNS
            or bare in _QUANTIFIERS
            or bare in _FUNCTION_WORDS
            or bare in _FUNDING_DESCRIPTORS
            or bare in _LISTING_ADJECTIVES
        ):
            continue
        if not token[0].isupper():
            continue
        return True, ["proper-noun token"]
    return False, []


def score_candidate_name(
    candidate: str | None,
    *,
    in_title: bool = False,
    in_heading: bool = False,
    in_anchor: bool = False,
    page_is_portal_index: bool = False,
    corpus_support: int = 0,
) -> ExtractionVerdict:
    """Judge one candidate scholarship name against the page it came from.

    Args:
        candidate: The raw candidate string. None/blank is always rejected.
        in_title: The string appeared in the page ``<title>``.
        in_heading: The string appeared in an h1–h3.
        in_anchor: The string was the text of a link.
        page_is_portal_index: The page is an index/listing rather than a
            single scholarship's detail page.
        corpus_support: How many independent heading/anchor occurrences of
            the same normalized name appeared on the page. Repeated
            occurrence is weak evidence of identity; once is not.

    Returns:
        An :class:`ExtractionVerdict`. ``accepted`` is a *routing* decision
        for the extraction stage only. Publication remains a human decision.
    """
    name = strip_site_suffix(_strip_punctuation_edges(_collapse(candidate or "")))
    if not name:
        return ExtractionVerdict(False, 0.0, ["empty candidate"], None)

    # Judge what the string claims, not the chrome wrapped around it.
    judged = _strip_ui_suffix(_strip_ui_prefix(name))

    reasons: list[str] = list(name_genericities(name))
    if not _names_an_opportunity(judged):
        reasons.append("names no scholarship or funding opportunity")

    # A heading/anchor is real evidence of "this page is about this thing".
    # Nothing at all means the string came from body prose.
    if in_title:
        reasons.append("appears in page title")
    if in_heading:
        reasons.append("appears as a page heading")
    if in_anchor:
        reasons.append("appears as a link label")
    if not (in_title or in_heading or in_anchor):
        reasons.append("no title/heading/anchor context")

    if page_is_portal_index:
        # On an index page the heading describes the *index*, not one
        # scholarship. This alone should not reject — real scholarship names
        # do appear in index listings — but it caps confidence.
        reasons.append("page is an index/listing, not a scholarship detail page")

    has_identity, identity_hits = has_identity_tokens(judged)
    canonical_shape = _has_canonical_name_shape(judged)
    if canonical_shape:
        reasons.append("canonical <name> + <opportunity> shape")
    if not has_identity:
        reasons.append("no year, acronym, organisation, programme qualifier or specific token")

    # ---- confidence -----------------------------------------------------
    confidence = 0.0
    identity_kind = ""
    if has_identity:
        identity_kind = (identity_hits or [""])[0]
        # A structural token (year, acronym, non-Latin script) is decisive.
        # A bare proper noun is suggestive and needs page context too.
        confidence += 0.45 if identity_kind != "proper-noun token" else 0.30
    if canonical_shape:
        # "ProperNoun + Scholarship" is the shape a real programme name
        # takes far more often than portal chrome does.
        confidence += 0.15
    if in_title:
        confidence += 0.20
    if in_heading:
        confidence += 0.18
    if in_anchor:
        confidence += 0.20
    if len(name) >= 18:
        confidence += 0.07
    elif len(name) >= 10:
        confidence += 0.04
    if corpus_support >= 2:
        confidence += 0.05
    if page_is_portal_index:
        confidence -= 0.15

    # Genericity is a hard disqualifier regardless of how the string scored
    # elsewhere: a name that names no programme is never publishable.
    generic = any(
        r.startswith(
            (
                "names only",
                "names no scholarship",
                "navigation/UI",
                "explicit unknown",
                "too short",
                "reads as",
                "describes a page section",
                "section label, not a programme name",
                "names a funding policy or system",
                "set in capitals",
                "page-type label followed",
            )
        )
        for r in reasons
    )
    no_context = "no title/heading/anchor context" in reasons
    no_identity = "no year, acronym" in reasons

    if generic:
        accepted = False
    elif no_context and no_identity:
        accepted = False
    else:
        accepted = confidence >= CONFIDENCE_ACCEPT

    confidence = max(0.0, min(1.0, round(confidence, 3)))

    if accepted:
        reasons.append(f"confidence {confidence} >= {CONFIDENCE_ACCEPT}")
    else:
        # A rejected candidate carries no confidence: reporting 0.7 on a
        # string we are refusing to publish would misrepresent the evidence.
        confidence = min(confidence, CONFIDENCE_ACCEPT - 0.01)

    return ExtractionVerdict(
        accepted=accepted,
        confidence=confidence,
        reasons=reasons,
        normalized_name=name if accepted else None,
    )


def normalize_scholarship_name(name: str) -> str:
    """Canonical form used inside ``scholarship.identity_key``.

    Shared by acquisition and review so two spellings of one scholarship
    collapse to one identity instead of two rows.
    """
    name = unicodedata.normalize("NFKC", _strip_punctuation_edges(_collapse(name)))
    name = _WHITESPACE.sub(" ", name).casefold()
    return name
