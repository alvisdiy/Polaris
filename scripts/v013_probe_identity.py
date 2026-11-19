"""READ-ONLY probe: what does a canonical name collapse on the live corpus?

Nothing here writes. It answers one question before any code is changed:
how many of the 21 duplicate-``official_page_url`` groups are genuinely the
same scholarship differing only in name formatting, and how many are
distinct awards that happen to share a page.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from sqlalchemy import select

from database.models.scholarship import Scholarship
from database.session import SessionLocal

_WS = re.compile(r"\s+")
_PUNCT_EDGES = " \t\r\n.·:-–—,;|/'\"()[]{}!?+*=_"


def canonical(name: str) -> str:
    """Proposed canonical form. Digits are deliberately preserved."""
    text = unicodedata.normalize("NFKC", name or "")
    text = text.replace("&", " and ")
    text = text.strip(_PUNCT_EDGES)
    text = _WS.sub(" ", text).strip()
    text = text.casefold()
    return text


def drop_self_repeat(text: str) -> str:
    """Remove a second copy of a leading segment inside the same name.

    ``"SP Scholarship and SP Engineering Scholarship The SP Scholarship and
    SP Engineering Scholarship"`` -> ``"sp scholarship and sp engineering
    scholarship"``. Page titles that concatenate the site heading with the
    H1 produce exactly this shape.
    """
    words = text.split()
    for size in range(len(words) // 2, 0, -1):
        head = " ".join(words[:size])
        rest = words[size:]
        if rest[:1] == ["the"]:
            rest = rest[1:]
        if " ".join(rest[:size]) == head:
            return head
    return text


def full(name: str) -> str:
    return drop_self_repeat(canonical(name))


def main() -> None:
    session = SessionLocal()
    rows = session.execute(select(Scholarship)).scalars().all()
    print(f"rows: {len(rows)}")

    # ---- how many rows does canonicalization alone change? ----
    changed = [r for r in rows if canonical(r.scholarship_name or "") != (r.scholarship_name or "").casefold()]
    print(f"rows whose canonical name differs from a plain casefold: {len(changed)}")

    # ---- would the new key collide among rows that are distinct today? ----
    groups: dict[str, list[Scholarship]] = defaultdict(list)
    for r in rows:
        key = f"{r.provider_id}|{full(r.scholarship_name or '')}|{r.country_id}"
        groups[key].append(r)
    collisions = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"canonical-key collision groups: {len(collisions)}")

    # ---- the 21 shared-URL groups, judged under the canonical name ----
    by_url: dict[str, list[Scholarship]] = defaultdict(list)
    for r in rows:
        if r.official_page_url:
            by_url[r.official_page_url].append(r)

    same, distinct = [], []
    for url, group in by_url.items():
        if len(group) < 2:
            continue
        keys = {full(r.scholarship_name or "") for r in group}
        (same if len(keys) == 1 else distinct).append((url, group, keys))

    print(f"\nshared-URL groups: {len(same) + len(distinct)}")
    print(f"  collapse to one identity : {len(same)}")
    print(f"  remain distinct          : {len(distinct)}")

    print("\n-- would collapse --")
    for url, group, keys in same:
        statuses = sorted({r.extraction_status for r in group})
        print(f"  [{len(group)}] {'/'.join(statuses):28} {url[:78]}")
        for r in group:
            print(f"        {str(r.scholarship_id)[:8]} {r.extraction_status:14} {r.scholarship_name!r}")
        print(f"        -> {list(keys)[0]!r}")

    print("\n-- must NOT collapse (distinct awards, one page) --")
    for url, group, keys in distinct:
        statuses = sorted({r.extraction_status for r in group})
        print(f"  [{len(group)}] {'/'.join(statuses):28} {url[:78]}")
        for r in group:
            print(f"        {str(r.scholarship_id)[:8]} {r.extraction_status:14} {r.scholarship_name!r}")

    # ---- year / cycle must survive canonicalization ----
    print("\n-- year preservation --")
    for a, b in [
        ("Fulbright Scholarship 2026", "Fulbright Scholarship 2027"),
        ("Chevening Scholarship", "Chevening Scholarship"),
        ("Global Excellence Scholarship", "Global Excellence Research Scholarship"),
    ]:
        print(f"  {a!r:42} -> {full(a)!r}")
        print(f"  {b!r:42} -> {full(b)!r}")
        print(f"  distinct: {full(a) != full(b)}")

    session.close()


if __name__ == "__main__":
    main()
