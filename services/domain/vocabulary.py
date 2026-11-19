"""Controlled vocabularies — the one authoritative definition in Polaris.

M9.1 Phase 4. Before this module the same degree list was written out in four
places, and they had already drifted: `real_extractor` could emit "Doctorate",
which `ingestion/validator` then rejected. A reviewer could type any string at
all into a field the matching engine treats as a category, and the live
Singapore record carries the result — an APPROVED scholarship with
``degree = "Polytechnic"``.

The invariant this module establishes:

    one semantic vocabulary, defined once, imported by every boundary.

It lives here rather than in `api/` or `services/matching/` because all of those
need it: API schemas describe the accepted values, the ingestion validator
checks them, the profile normalizer maps to them, the review service refuses
everything else, and the database migration generates its constraint from them.
A vocabulary owned by any one of those layers would just move the duplication.

Design rules
------------
**Categories are declared, not derived.** A value is in the vocabulary because
the domain says so, not because it looks like another value.

**Unknown is representable.** Every controlled field is nullable, and NULL
means "the source did not state this". That is a real, useful answer — the
alternative, inventing a category to fill the gap, is what produced
"Polytechnic" in the first place.

**Normalisation is explicit and auditable.** ``normalize_*`` maps only
terminology that is genuinely the same thing ("master's" → Master). It returns
None for anything else instead of guessing, and callers record what was
normalized in provenance so the source wording is never lost.

See ADR-016 for the reasoning behind the degree decision, in particular why
"diploma" is deliberately NOT mapped to Bachelor.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Degree level
# ---------------------------------------------------------------------------
# The canonical set, as declared in docs/v0.1/data-dictionary.md ("## Degree").
# Ordered from lowest to highest level so anything rendering this can rely on
# the order; membership tests should use DEGREE_VALUES.
DEGREE_LEVELS: tuple[str, ...] = (
    "Bachelor",
    "Exchange",
    "Master",
    "PhD",
    "Short Course",
)
DEGREE_VALUES: frozenset[str] = frozenset(DEGREE_LEVELS)

# Deterministic source terminology → canonical level.
#
# Every entry is a spelling variant of a value already in DEGREE_LEVELS. None
# of them bridges to a *different* level of study: that is the rule that keeps
# "diploma" out of this table. A Foundation Programme and a Bachelor's degree
# are not the same qualification, and mapping one onto the other would put a
# wrong value in front of a student deciding where to apply.
DEGREE_ALIASES: dict[str, str] = {
    # Bachelor
    "bachelor": "Bachelor",
    "bachelors": "Bachelor",
    "bachelor's": "Bachelor",
    "bachelors'": "Bachelor",
    "bachelor degree": "Bachelor",
    "b.sc.": "Bachelor",
    "bsc": "Bachelor",
    # Master
    "master": "Master",
    "masters": "Master",
    "master's": "Master",
    "masters'": "Master",
    "master degree": "Master",
    "m.sc.": "Master",
    "msc": "Master",
    "postgraduate": "Master",
    # PhD
    "phd": "PhD",
    "ph.d": "PhD",
    "ph.d.": "PhD",
    "doctorate": "PhD",
    "doctoral": "PhD",
    "doctor": "PhD",
    # Exchange
    "exchange": "Exchange",
    "exchange programme": "Exchange",
    "exchange program": "Exchange",
    # Short Course
    "short course": "Short Course",
    "shortcourse": "Short Course",
    "short-course": "Short Course",
    "certificate course": "Short Course",
}

# Qualification terminology that Polaris encounters in real sources and
# deliberately does NOT map to any degree level.
#
# These are not an oversight and not a TODO. Each names a real qualification
# that is not a Bachelor's degree: a polytechnic diploma or foundation
# programme sits below it, and a certificate course is not a degree at all.
# Forcing any of them into DEGREE_LEVELS would tell a student that a
# foundation programme is a degree they already hold, which is the kind of
# quiet inaccuracy that makes a knowledge base untrustworthy.
#
# They are listed so that the extraction and review layers can *detect* them
# and preserve the wording as evidence, rather than dropping the information or
# inventing a category for it.
UNMAPPED_QUALIFICATION_TERMS: tuple[str, ...] = (
    "diploma",
    "polytechnic",
    "foundation programme",
    "foundation program",
    "certificate",
    "certification",
    "post-diploma",
    "pgdip",
)

# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------
# The vocabulary covers what a page can actually *evidence* about coverage.
#
# It was three values, which forced three distinct real-world awards into one
# bucket: "tuition waiver" was an alias for "Tuition Only", so a page promising
# to waive tuition in full and a page covering fees only both published as the
# same thing.
#
# Adding a value needs more than editing this tuple. An earlier version of this
# comment claimed that `funding_type` being a `String(50)` column meant widening
# the vocabulary needed no migration, and that was wrong: the width only says
# what fits, not what is allowed. A CHECK constraint
# (``ck_scholarship_funding_type_vocabulary``) decides what is allowed, and it
# is created from this tuple by a migration. Widen the tuple without widening
# the constraint and the two disagree in the worst direction — the application
# resolves a real page's wording to a value the database then refuses, so the
# record is lost at INSERT with nothing pointing back at the vocabulary.
# ``e7f8a9b0c1d2`` reconciles the two; the alias map below is only the
# text-to-value half.
#
# "Unknown" is deliberately NOT a value. A NULL `funding_type` *means* unknown,
# and giving it a string would make "we did not find evidence" indistinguishable
# from "the source said unknown". This is the rule V0.1 established after
# finding 18 records publishing "Fully Funded" with no source wording at all:
# classify only when the page states it, otherwise leave it NULL.
FUNDING_TYPES: tuple[str, ...] = (
    "Fully Funded",
    "Partial Funded",
    "Tuition Only",
    "Tuition Waiver",
    "Stipend Only",
    "Living Allowance",
    "Travel Support",
    "Research Funding",
)
FUNDING_VALUES: frozenset[str] = frozenset(FUNDING_TYPES)

FUNDING_ALIASES: dict[str, str] = {
    "fully funded": "Fully Funded",
    "full": "Fully Funded",
    "full funding": "Fully Funded",
    "full scholarship": "Fully Funded",
    "complete funding": "Fully Funded",
    "fully-covered": "Fully Funded",
    "partial funded": "Partial Funded",
    "partial funding": "Partial Funded",
    "partial": "Partial Funded",
    "partial scholarship": "Partial Funded",
    "tuition only": "Tuition Only",
    "tuition-only": "Tuition Only",
    "fees only": "Tuition Only",
    "fee-only": "Tuition Only",
    "tuition waiver": "Tuition Waiver",
    "full tuition waiver": "Tuition Waiver",
    "waiver of tuition": "Tuition Waiver",
    "tuition-fee waiver": "Tuition Waiver",
    "stipend only": "Stipend Only",
    "stipend-only": "Stipend Only",
    "living allowance": "Living Allowance",
    "monthly allowance": "Living Allowance",
    "accommodation allowance": "Living Allowance",
    "travel grant": "Travel Support",
    "travel allowance": "Travel Support",
    "airfare": "Travel Support",
    "air fare": "Travel Support",
    "research funding": "Research Funding",
    "research grant": "Research Funding",
    "research allowance": "Research Funding",
}

# ---------------------------------------------------------------------------
# Experience levels (user profile + scholarship requirement)
# ---------------------------------------------------------------------------
EXPERIENCE_LEVELS: tuple[str, ...] = (
    "Required",
    "Preferred",
    "Optional",
    "Not Required",
)
EXPERIENCE_VALUES: frozenset[str] = frozenset(EXPERIENCE_LEVELS)

EXPERIENCE_ALIASES: dict[str, str] = {
    "required": "Required",
    "mandatory": "Required",
    "must": "Required",
    "preferred": "Preferred",
    "recommended": "Preferred",
    "desirable": "Preferred",
    "optional": "Optional",
    "not required": "Not Required",
    "not_required": "Not Required",
    "none": "Not Required",
}

# ---------------------------------------------------------------------------
# Scholarship type (controlled, but not used by matching)
# ---------------------------------------------------------------------------
SCHOLARSHIP_TYPES: tuple[str, ...] = (
    "Government",
    "University",
    "Foundation",
    "NGO",
    "Company",
)
SCHOLARSHIP_TYPE_VALUES: frozenset[str] = frozenset(SCHOLARSHIP_TYPES)

SCHOLARSHIP_TYPE_ALIASES: dict[str, str] = {
    "government": "Government",
    "governmental": "Government",
    "university": "University",
    "foundation": "Foundation",
    "ngo": "NGO",
    "non-governmental": "NGO",
    "non governmental organization": "NGO",
    "company": "Company",
    "corporate": "Company",
}


# ---------------------------------------------------------------------------
# The registry every boundary consults
# ---------------------------------------------------------------------------
class Vocabulary:
    """One controlled field: its allowed values and its normalizer.

    Bundling the set and the normalizer keeps them from drifting apart, which
    is the specific failure that produced "Doctorate".
    """

    def __init__(
        self,
        name: str,
        values: frozenset[str],
        order: tuple[str, ...],
        aliases: dict[str, str],
        *,
        nullable: bool = True,
        label: str = "",
    ) -> None:
        self.name = name
        self.values = values
        self.order = order
        self.aliases = aliases
        self.nullable = nullable
        self.label = label or name.replace("_", " ")

    def normalize(self, value) -> str | None:
        """Map source wording to a canonical value, or None if unrecognised.

        Never guesses. An unrecognised term returns None, which the caller must
        represent explicitly (usually as a NULL field plus preserved source
        evidence) rather than mapping to the nearest-looking category.
        """
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text in self.values:
            return text
        return self.aliases.get(text.lower())

    def is_valid(self, value) -> bool:
        if value is None:
            return self.nullable
        return str(value).strip() in self.values

    def suggest(self, value) -> str | None:
        """The canonical value a misspelling most likely meant, if unambiguous.

        Only used to build an error message. A wrong suggestion in a reviewer's
        face is harmless; a silent coercion is not, which is why this is never
        called on the write path.
        """
        if value is None:
            return None
        candidate = str(value).strip().lower()
        if candidate in self.aliases:
            return self.aliases[candidate]
        close = [
            canonical
            for key, canonical in self.aliases.items()
            if candidate and (candidate in key or key in candidate)
        ]
        if len(set(close)) == 1:
            return close[0]
        return None

    def describe(self) -> str:
        return ", ".join(sorted(self.values))


DEGREE = Vocabulary(
    "degree", DEGREE_VALUES, DEGREE_LEVELS, DEGREE_ALIASES, nullable=True,
    label="degree level",
)
FUNDING_TYPE = Vocabulary(
    "funding_type", FUNDING_VALUES, FUNDING_TYPES, FUNDING_ALIASES, nullable=True,
    label="funding type",
)
EXPERIENCE = Vocabulary(
    "experience_level", EXPERIENCE_VALUES, EXPERIENCE_LEVELS, EXPERIENCE_ALIASES,
    nullable=True, label="experience level",
)
SCHOLARSHIP_TYPE = Vocabulary(
    "scholarship_type", SCHOLARSHIP_TYPE_VALUES, SCHOLARSHIP_TYPES,
    SCHOLARSHIP_TYPE_ALIASES, nullable=True, label="scholarship type",
)

CONTROLLED_VOCABULARIES: dict[str, Vocabulary] = {
    vocabulary.name: vocabulary
    for vocabulary in (DEGREE, FUNDING_TYPE, EXPERIENCE, SCHOLARSHIP_TYPE)
}

# Alias so the schema field name and the registry key agree even though the
# matching spec calls this an experience "level".
EXPERIENCE_LEVEL = EXPERIENCE


def get(field: str) -> Vocabulary | None:
    """The Vocabulary for a field name, or None if it is free text."""
    return CONTROLLED_VOCABULARIES.get(field)


class InvalidVocabularyValue(ValueError):
    """A controlled field was given a value outside its vocabulary.

    Carries the full context a caller needs to act on it: which field, which
    value was refused, what is allowed, and whether leaving it empty is
    legitimate. A reviewer seeing this should be able to fix the problem
    without consulting the source code.
    """

    def __init__(
        self,
        field: str,
        value,
        vocabulary: Vocabulary,
        *,
        suggestion: str | None = None,
    ) -> None:
        self.field = field
        self.value = value
        self.vocabulary = vocabulary
        self.suggestion = suggestion

        allowed = ", ".join(vocabulary.order)
        parts = [
            f"invalid {vocabulary.label}: {value!r}",
            f"allowed values are: {allowed}",
        ]
        if vocabulary.nullable:
            parts.append("this field may also be left empty if the source does not state it")
        if suggestion:
            parts.append(f"did you mean {suggestion!r}?")
        super().__init__(". ".join(parts) + ".")


def validate(field: str, value, *, allow_none: bool = True) -> None:
    """Raise InvalidVocabularyValue unless `value` is acceptable for `field`.

    Deliberately strict: it accepts an already-canonical value or None, and
    refuses everything else. It does not normalize, because silently rewriting
    a reviewer's input would make the audit trail record a change they did not
    make. Normalization belongs at extraction time, where the source wording is
    available to record alongside the canonical value.
    """
    vocabulary = CONTROLLED_VOCABULARIES.get(field)
    if vocabulary is None:
        return  # free text: nothing to enforce
    if value is None and (allow_none or vocabulary.nullable):
        return
    if not vocabulary.is_valid(value):
        raise InvalidVocabularyValue(
            field, value, vocabulary, suggestion=vocabulary.suggest(value)
        )


def is_valid(field: str, value) -> bool:
    vocabulary = CONTROLLED_VOCABULARIES.get(field)
    if vocabulary is None:
        return True
    return vocabulary.is_valid(value)


def normalize(field: str, value) -> str | None:
    """Canonicalize `value` for `field`, or None when it is not recognised."""
    vocabulary = CONTROLLED_VOCABULARIES.get(field)
    if vocabulary is None:
        return str(value).strip() if value is not None else None
    return vocabulary.normalize(value)


UNMAPPED_QUALIFICATION_NOTE = (
    "source states a qualification with no canonical degree level; "
    "left empty rather than mapped to an unsupported value"
)


def qualifies_as_unmapped_qualification(text: str | None) -> str | None:
    """The source term for a qualification Polaris will not map, if present.

    Lets the extraction layer say "the page says diploma, and Polaris has no
    category for it" instead of either inventing one or staying silent. The
    returned wording is evidence, not a value.
    """
    if not text:
        return None
    lowered = str(text).lower()
    for term in UNMAPPED_QUALIFICATION_TERMS:
        if term in lowered:
            return term
    return None
