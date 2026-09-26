"""Freshness classification for scholarship deadlines.

The Knowledge Base must never present an obviously expired scholarship as a
current opportunity just because it was discovered recently. This module owns
the deadline state machine:

  - deadline in the future            → active
  - deadline already passed           → expired
  - no deadline on the page           → unknown  (never fabricated)
  - rolling / open-until-filled /
    open until further notice         → rolling  (semantics preserved)

The classifier is intentionally conservative: it only trusts an extracted
deadline when the page text actually supports it, and it never invents dates.
Dates are distinguished by meaning, never conflated:

  discovered_at  (first seen)  — TimestampMixin.created_at on the row
  fetched_at    (page fetch)   — RawDocument.fetched_at
  deadline      (application)  — ScholarshipTimeline.application_deadline
  cycle/year    (cohort)       — ScholarshipTimeline.application_cycle
"""

from __future__ import annotations

import re
from datetime import date

# Page phrases that mean the application window does not close on a fixed date.
# These must win over naive date extraction, because a page saying
# "applications accepted until all positions are filled" is not a deadline page.
_ROLLING_PATTERNS = (
    r"rolling\s+(?:admissions?|basis|deadline)",
    r"open\s+until\s+(?:all\s+)?(?:positions?|slots?|places?|funds?\s+are\s+exhausted|filled)",
    r"until\s+(?:all\s+)?(?:positions?|slots?)\s+(?:are\s+)?filled",
    r"open\s+(?:all\s+year|year[-\s]?round|throughout\s+the\s+year)",
    r"no\s+(?:application\s+)?deadline",
    r"applications?\s+(?:are\s+)?(?:accepted|reviewed)\s+on\s+a\s+rolling\s+basis",
)

STATE_ACTIVE = "active"
STATE_EXPIRED = "expired"
STATE_UNKNOWN = "unknown"
STATE_ROLLING = "rolling"


def detect_rolling(text: str) -> bool:
    """True when the page text expresses open-ended application semantics."""
    lowered = (text or "").lower()
    return any(re.search(p, lowered) for p in _ROLLING_PATTERNS)


def classify_deadline(
    deadline: date | None,
    *,
    page_text: str = "",
    today: date | None = None,
) -> str:
    """Classify one scholarship's deadline state.

    Rules (in order):
      1. Page expresses rolling/open-ended semantics → rolling, even if a
         heuristic date was also extracted (the phrase is the stronger claim).
      2. No deadline anywhere → unknown (never invented).
      3. Deadline in the future (or today) → active.
      4. Deadline in the past → expired.
    """
    if detect_rolling(page_text):
        return STATE_ROLLING
    if deadline is None:
        return STATE_UNKNOWN
    reference = today or date.today()
    return STATE_ACTIVE if deadline >= reference else STATE_EXPIRED


def condense_observations(observations: list[dict], limit: int = 20) -> dict:
    """Condense append-only provenance observations into bounded history.

    Per-URL snapshots collapse into one entry per URL: first_seen, last_seen,
    latest label, and how many times the URL was re-observed. Runs stay
    bounded on long-lived ecosystems instead of growing forever.
    """
    by_url: dict[str, dict] = {}
    for obs in observations or []:
        url = str(obs.get("url") or "")[:2048]
        if not url:
            continue
        at = str(obs.get("at") or "")
        entry = by_url.setdefault(
            url,
            {"url": url, "first_seen": at, "last_seen": at, "times_seen": 0, "latest": {}},
        )
        entry["last_seen"] = max(entry["last_seen"], at) if at else entry["last_seen"]
        entry["first_seen"] = (
            min(entry["first_seen"], at)
            if at and entry["first_seen"]
            else (at or entry["first_seen"])
        )
        entry["times_seen"] += 1
        latest = {k: v for k, v in obs.items() if k not in ("url", "at")}
        if latest:
            entry["latest"] = latest

    condensed = sorted(by_url.values(), key=lambda e: e["last_seen"], reverse=True)
    for entry in condensed:
        if not entry["latest"]:
            entry.pop("latest")
    return {"observations": condensed[:limit], "total_condensed": len(by_url)}
