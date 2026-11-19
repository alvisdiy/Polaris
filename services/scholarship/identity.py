"""Canonical scholarship identity.

One place decides what "the same scholarship" means. Every creation path —
acquisition, the generic ingestion orchestrator, seed scripts — routes through
:func:`scholarship_identity_key`, so identity cannot depend on which path a
record arrived by.

Two rules govern the design:

* **Deterministic.** No fuzzy matching, no edit distance, no learned
  similarity. The same inputs always produce the same key, on any machine, in
  any process, forever. A merge that cannot be proved is not performed.
* **A year is part of the name, not decoration.** ``Fulbright Scholarship
  2026`` and ``Fulbright Scholarship 2027`` are different application cycles
  and must never collapse. Digit stripping would silently merge cycles.

``country_id`` stays in the key. It is the effective study destination —
either the country the page states, or, when the page states none, the
source's country. That fallback means the same international scholarship
found from two country runs *could* split; ``detect_cross_country_clones``
exists so that case is visible rather than silent. See
``docs/progress/SCHOLARSHIP-IDENTITY-HARDENING.md``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from services.ingestion.extraction_quality import (
    _FUNDING_NOUNS,
    _collapse,
    _strip_punctuation_edges,
    substantive_words,
)

__all__ = [
    "IdentityUnavailable",
    "canonical_scholarship_name",
    "canonical_url",
    "scholarship_identity_key",
    "assess_duplicate",
    "detect_cross_country_clones",
]


_WHITESPACE = re.compile(r"\s+")

# Only the definite article. "The Rhodes Scholarship" and "Rhodes Scholarship"
# are the same award, but "A Star Scholarship" and "Star Scholarship" are two
# different ones — an indefinite article carries that much meaning, so it is
# left alone.
_LEADING_ARTICLE = "the"

# Query parameters that identify the referrer, never the destination page.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "utm_source_platform", "utm_creative_format",
        "utm_marketing_tactic", "gclid", "fbclid", "msclkid", "dclid",
        "yclid", "mc_cid", "mc_eid", "igshid", "ref", "referrer", "source",
        "spm", "scm", "share", "share_id", "trk", "trkCampaign",
    }
)


class IdentityUnavailable(Exception):
    """The row does not carry enough to compute an identity.

    Raised instead of returning a hash of empty strings, because a key built
    from ``None`` is a key that silently collides with every other row
    missing the same field.
    """


def _fold(name: str) -> str:
    """NFKC + whitespace + edge punctuation + casefold, before any rule.

    Edge punctuation is trimmed with the extraction layer's *balanced* helper:
    the trailing ``)`` in "DAAD Courses (EPOS)" is part of the name, while the
    one in "Eiffel Scholarship )" is chrome. A naive ``strip("()")`` destroys
    the first kind.
    """
    text = unicodedata.normalize("NFKC", name or "")
    text = text.replace("&", " and ")
    text = _collapse(_strip_punctuation_edges(text))
    # Brackets are the balanced helper's business; these never pair with
    # anything, so trimming them cannot unbalance a name.
    text = text.strip("!?+$%^~`")
    return text.casefold()


def _drop_repeated_leading_segment(words: list[str]) -> list[str]:
    """Collapse ``<name> <name>`` into one copy.

    A page whose ``<title>`` is the site heading plus the ``<h1>`` extracts
    as "SP Scholarship and SP Engineering Scholarship The SP Scholarship and
    SP Engineering Scholarship". Both halves are the same string, so the
    shorter one is provably the name.
    """
    for size in range(len(words) // 2, 0, -1):
        head = words[:size]
        rest = words[size:]
        if rest[:1] == [_LEADING_ARTICLE]:
            rest = rest[1:]
        if rest[:size] == head:
            return head
    return words


def _drop_glued_trailing_segment(name: str) -> str:
    """Drop a trailing line that adds no content the earlier lines lack.

    A page that joins its ``<h1>`` and ``<title>`` with a newline extracts as
    "Opportunity Scholarship\\nScholarship" — two lines, one name. The newline
    is the evidence: a name typed on a single line that happens to end in
    "Scholarship Scholarship" gets no such benefit, because there the second
    copy might be a real title.

    The test is whether every substantive word of the last line already
    appears in the lines before it, so "Sanctuary Scholarship" is dropped
    after "Loughborough University Sanctuary Scholarships" (sanctuary is
    already said) while "Beasiswa Reguler (PhD)" is kept after "Beasiswa
    Reguler" (phd is not).
    """
    lines = [line for line in name.replace("\r", "\n").split("\n") if line.strip()]
    if len(lines) < 2:
        return name

    head, tail = "\n".join(lines[:-1]), lines[-1]
    tail_words = substantive_words(tail)

    # A tail that is nothing but a generic funding noun adds nothing, whatever
    # the head was: "Opportunity Scholarship\nScholarship" is one name.
    if not tail_words and canonical_scholarship_name(tail) in _FUNDING_NOUNS:
        return head

    earlier_words = set(substantive_words(head))
    if tail_words and earlier_words and all(word in earlier_words for word in tail_words):
        return head
    return name


def _is_funding_noun(word: str) -> bool:
    return word in _FUNDING_NOUNS


def _singularize_funding_noun(word: str) -> str | None:
    """``scholarships`` -> ``scholarship`` when the singular is also a noun.

    Only applied to a trailing funding noun, so "Sport Scholarships" and
    "Sport Scholarship" collapse while "Studies" and "Study" — neither of
    which is a funding noun — are untouched.
    """
    if word.endswith("s") and not word.endswith("ss"):
        singular = word[:-1]
        if _is_funding_noun(singular):
            return singular
    return None


def canonical_scholarship_name(name: str) -> str:
    """Return the canonical form of a scholarship name.

    Applied identically wherever identity is computed, so two spellings of
    one scholarship collapse and two genuinely different scholarships do not.
    """
    text = _fold(_drop_glued_trailing_segment(name))
    if not text:
        return ""

    words = text.split(" ")
    words = words[1:] if words[:1] == [_LEADING_ARTICLE] else words
    if not words:
        return ""

    words = _drop_repeated_leading_segment(words)

    # "Sport Scholarships" and "Sport Scholarship" are one programme. The
    # rewrite runs on both sides of a comparison, so it is symmetric.
    if words:
        singular = _singularize_funding_noun(words[-1])
        if singular is not None:
            words[-1] = singular

    text = " ".join(words)
    return _WHITESPACE.sub(" ", _collapse(_strip_punctuation_edges(text))).strip("!?+$%^~`")


def canonical_url(url: str | None) -> str | None:
    """Return a comparable form of a page URL.

    Used only to *detect* likely duplicates — never as identity. The live
    corpus proves why: four distinct MEXT awards and two distinct LPDP
    awards share one ``official_page_url``, so a URL key would merge real
    programmes.
    """
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.netloc:
        return None

    scheme = (parts.scheme or "https").casefold()
    netloc = parts.netloc.casefold()
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[: -len(":443")]
    elif netloc.endswith(":80") and scheme == "http":
        netloc = netloc[: -len(":80")]

    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.casefold() not in _TRACKING_PARAMS
    ]
    # Sorted so parameter order never decides equality. The values stay:
    # a `?id=` or `?lang=` selects a different page and must not be folded away.
    query = urlencode(sorted(kept), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def scholarship_identity_key(provider_id, name: str, country_id) -> str:
    """Return the canonical dedup hash for one scholarship.

    Args:
        provider_id: Owning provider. Two scholarships from one provider are
            the only pair the name can be trusted to disambiguate.
        name: The scholarship name as extracted; canonicalized here.
        country_id: Effective study destination. Part of the key because the
            same programme genuinely differs per country — see the module
            docstring.

    Raises:
        IdentityUnavailable: if any component is missing. A missing
            component must not become part of a hash; it must stay visible.
    """
    if provider_id is None:
        raise IdentityUnavailable("provider_id is required for identity")
    if country_id is None:
        raise IdentityUnavailable("country_id is required for identity")
    canonical = canonical_scholarship_name(name)
    if not canonical:
        raise IdentityUnavailable("scholarship name is required for identity")
    payload = f"{provider_id}|{canonical}|{country_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assess_duplicate(session, *, canonical_key: str, exclude_id=None):
    """Return the existing row that already owns this identity, or ``None``.

    ``canonical_key`` is supplied by the caller rather than recomputed so
    that the key which was *written* is the key which was *checked*.
    """
    from database.models.scholarship import Scholarship

    query = session.query(Scholarship).filter(Scholarship.identity_key == canonical_key)
    if exclude_id is not None:
        query = query.filter(Scholarship.scholarship_id != exclude_id)
    return query.first()


def detect_cross_country_clones(session) -> list[tuple[str, str, str, str]]:
    """Find one scholarship split across countries by discovery scope.

    Returns ``(canonical_name, provider_id, country_a, country_b)`` tuples.
    This is a *report*, not a merge: which of the two rows is the real
    scholarship is not provable from the data, so the decision belongs to a
    human.
    """
    from database.models.scholarship import Scholarship

    grouped: dict[tuple[str, str], set[str]] = {}
    for row in session.query(Scholarship.provider_id, Scholarship.scholarship_name, Scholarship.country_id):
        canonical = canonical_scholarship_name(row.scholarship_name or "")
        if canonical:
            grouped.setdefault((str(row.provider_id), canonical), set()).add(str(row.country_id))

    clones: list[tuple[str, str, str, str]] = []
    for (provider_id, canonical), countries in sorted(grouped.items()):
        for i, first in enumerate(sorted(countries)):
            for second in sorted(countries)[i + 1 :]:
                clones.append((canonical, provider_id, first, second))
    return clones
