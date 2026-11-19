"""Canonical lifecycle vocabulary for sources and providers.

The same column was written in two spellings and read in a third:

* seed/registration wrote ``status='active'`` and
  ``verification_status='unverified'``;
* the per-country orchestrators filtered ``"Active"``/``"Provisional"`` and
  ``discovered/candidate/verified``.

The result was not a cosmetic mismatch. Seeded sources were invisible to every
discovery path, so a country run reported "0 sources" against a database that
contained five. This module is the one place the spellings are defined and
normalised; callers compare against the constants and normalise input at the
boundary.
"""

from __future__ import annotations

# --- Source status ---------------------------------------------------------

SOURCE_ACTIVE = "Active"
SOURCE_PROVISIONAL = "Provisional"
SOURCE_RETIRED = "Retired"

SOURCE_STATUSES = (SOURCE_ACTIVE, SOURCE_PROVISIONAL, SOURCE_RETIRED)
SOURCE_ACTIVE_STATES = (SOURCE_ACTIVE, SOURCE_PROVISIONAL)

_SOURCE_ALIASES = {
    "active": SOURCE_ACTIVE,
    "provisional": SOURCE_PROVISIONAL,
    "retired": SOURCE_RETIRED,
    "inactive": SOURCE_RETIRED,
    "deprecated": SOURCE_RETIRED,
}

# --- Provider verification status -----------------------------------------

PROVIDER_DISCOVERED = "discovered"
PROVIDER_CANDIDATE = "candidate"
PROVIDER_VERIFIED = "verified"
PROVIDER_REGISTERED = "registered"
PROVIDER_REJECTED = "rejected"
PROVIDER_DEPRECATED = "deprecated"

_PROVIDER_ALIASES = {
    "unverified": PROVIDER_DISCOVERED,
    "new": PROVIDER_DISCOVERED,
    "pending": PROVIDER_DISCOVERED,
    "needs_review": PROVIDER_CANDIDATE,
    "approved": PROVIDER_VERIFIED,
    "deprecated": PROVIDER_DEPRECATED,
}


def normalize_source_status(value: str | None) -> str:
    """Return the canonical source status for ``value``.

    Unknown values are returned unchanged rather than guessed into a known
    state: a typo should be visible in the database, not silently turned into
    "Active".
    """
    raw = (value or "").strip()
    if not raw:
        return SOURCE_ACTIVE
    return _SOURCE_ALIASES.get(raw.casefold(), raw)


def normalize_provider_status(value: str | None) -> str:
    """Return the canonical provider verification status for ``value``."""
    raw = (value or "").strip()
    if not raw:
        return PROVIDER_DISCOVERED
    return _PROVIDER_ALIASES.get(raw.casefold(), raw.casefold())


def source_is_active(value: str | None) -> bool:
    """Whether a source status participates in acquisition (any spelling)."""
    return normalize_source_status(value) in SOURCE_ACTIVE_STATES
