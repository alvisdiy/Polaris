"""Declared award levels when a page states several of them.

A page can state one level ("This scholarship is for Master's students"), and
``degree`` already handles that. This module answers the other case: a page that
publishes a *set* of levels as a labelled field.

    Academic level:
    Doctoral degree program
    Master's degree program

That is a statement about the award, not a list of what applicants may hold. The
distinction is the whole reason this is separate from the prose scan: "an
existing Master's degree ... a Doctoral qualification" is an eligibility list,
and turning that into "this award is for Master and PhD" would put a wrong
filter value in front of a student.

So the levels are only collected when they sit inside a labelled block —
``Academic level``, ``Available programs``, ``Degree level``, ``Level of study``
— and only when the block's own lines yield at least two canonical levels. One
level found inside such a block is left to the single-value extractor, which
already knows how to record it.
"""

from __future__ import annotations

import re

from services.domain.vocabulary import DEGREE_ALIASES, DEGREE_VALUES

# The label a database uses for its "which levels is this award for" field.
# Only labels that name the award's level qualify; "Eligibility" and
# "Qualifications" deliberately do not, because those describe the applicant.
#
# Rendered pages prefix the label with a list bullet ("- Academic level:"), and
# the label can be a markdown heading. Both spellings are the same field.
_LEVEL_LABEL = re.compile(
    r"(?:^|\n)[ \t]*(?:[-*•][ \t]*)?(?:#{1,6}[ \t]*)?"
    r"(?:academic level|available programs?|available programmes?|"
    r"degree level|level of study|study level|programme level|program level)"
    r"[ \t]*:?[ \t]*(?=\n|$)",
    re.IGNORECASE,
)

# A label in the same shape as the one that opened the block: any short line
# ending in a colon. The block ends there, so a following "Special notes:" or
# "Eligibility:" cannot contribute levels to the award.
_NEXT_LABEL = re.compile(r"^[^\n:]{1,60}:$")


def _levels_in(text: str) -> list[str]:
    """Canonical levels named in ``text``, in declaration order."""
    found: list[str] = []
    lowered = text.lower()
    for alias, canonical in sorted(
        DEGREE_ALIASES.items(), key=lambda item: -len(item[0])
    ):
        if alias in lowered and canonical not in found:
            found.append(canonical)
    return [level for level in found if level in DEGREE_VALUES]


def declared_award_levels(text: str, *, max_chars: int = 400) -> list[str]:
    """Levels an award is offered for, when the page lists them under a label.

    Returns an empty list when no labelled block exists, or when the block names
    fewer than two levels (a single level is the single-value path's job).
    """
    for match in _LEVEL_LABEL.finditer(text or ""):
        window = text[match.end() : match.end() + max_chars]
        block: list[str] = []
        for line in window.splitlines():
            stripped = line.strip().lstrip("-*• ").strip()
            if not stripped:
                if block:
                    break
                continue
            if block and _NEXT_LABEL.match(stripped):
                break
            block.append(stripped)
            if len(block) >= 8:
                break
        levels = _levels_in("\n".join(block))
        if len(levels) > 1:
            return levels
    return []
