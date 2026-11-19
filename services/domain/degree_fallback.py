"""Infer a degree level from evidence the page already carries.

The level is a soft field now, so a record without one is still publishable.
That removes the pressure to guess — and this module keeps to the narrow set of
cases where there is no guess involved:

* the programme's own name says "PhD", "Master's", "Bachelor's", "Erasmus
  exchange", and says exactly one of them;
* the official page's path sits under a section named for one level
  (``/phd/``, ``/masters/``, ``/undergraduate/``).

Two signals that disagree are not resolved here. "Postgraduate" is deliberately
absent from the table: at a British university it covers both Master's and PhD,
and mapping it to Master would put a wrong filter value on half the records it
touches. A record that cannot be read unambiguously keeps NULL, which the UI and
the matching engine both understand.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from services.domain.vocabulary import DEGREE_VALUES

# Ordered most specific first: a name containing both "Master" and "PhD" is a
# multi-level award, which is a different answer than "pick the first match".
_NAME_SIGNALS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bph\.?\s?d\b|\bdoctoral\b|\bdoctorate\b", re.IGNORECASE), "PhD"),
    (re.compile(r"\bmaster'?s?\b|\bm\.?sc\b|\bmba\b|\bmpa\b|\bm\.?a\.?\b", re.IGNORECASE), "Master"),
    (re.compile(r"\bbachelor'?s?\b|\bundergraduate\b|\bb\.?sc\b|\bb\.?a\.?\b", re.IGNORECASE), "Bachelor"),
    (re.compile(r"\berasmus\b|\bexchange\b", re.IGNORECASE), "Exchange"),
    (re.compile(r"\bshort\s+course\b|\bsummer\s+school\b", re.IGNORECASE), "Short Course"),
)

# Path segments that name a level outright. Matched against whole segments so
# "/phd-studentship" and "/phd/" both count while "/phdnews" does not.
_PATH_SIGNALS: tuple[tuple[str, str], ...] = (
    ("phd", "PhD"),
    ("doctoral", "PhD"),
    ("doctorate", "PhD"),
    ("masters", "Master"),
    ("master", "Master"),
    ("undergraduate", "Bachelor"),
    ("bachelors", "Bachelor"),
    ("bachelor", "Bachelor"),
    ("exchange", "Exchange"),
)


def _levels_in_name(name: str) -> list[str]:
    found: list[str] = []
    for pattern, level in _NAME_SIGNALS:
        if pattern.search(name) and level not in found:
            found.append(level)
    return [level for level in found if level in DEGREE_VALUES]


def _levels_in_path(url: str) -> list[str]:
    try:
        path = urlparse(url or "").path.lower()
    except ValueError:
        return []
    segments = {segment for segment in re.split(r"[/_\-]+", path) if segment}
    found: list[str] = []
    for segment, level in _PATH_SIGNALS:
        if segment in segments and level not in found:
            found.append(level)
    return [level for level in found if level in DEGREE_VALUES]


def infer_degree(name: str | None, official_page_url: str | None) -> str | None:
    """One level when the evidence names exactly one, otherwise None."""
    from_name = _levels_in_name(name or "")
    from_url = _levels_in_path(official_page_url or "")

    if len(from_name) == 1 and not from_url:
        return from_name[0]
    if not from_name and len(from_url) == 1:
        return from_url[0]
    if len(from_name) == 1 and len(from_url) == 1 and from_name[0] == from_url[0]:
        return from_name[0]
    # Two signals disagreeing, or a name naming several levels, is a set or a
    # contradiction. Neither is this function's call.
    return None


def infer_degree_levels(name: str | None, official_page_url: str | None) -> list[str]:
    """The award's levels when the name names several of them.

    "PhD and Master's Scholarships" is a multi-level award stated in the name;
    recording it as a set keeps the record filterable without pretending it has
    one level.
    """
    from_name = _levels_in_name(name or "")
    if len(from_name) > 1:
        return from_name
    return []
