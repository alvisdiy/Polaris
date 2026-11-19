"""The publication boundary, in one place.

Everything a user can see passes through one predicate: a scholarship is public
if and only if ``extraction_status == PUBLISHED_STATE``.

That rule used to be written out three times (two repository methods plus the
matching service's repository call). Three copies of a visibility rule is three
places to forget one, and the failure mode is severe: a pending or rejected
record leaking into recommendations is exactly what M9 exists to prevent.
A fourth copy survived in the public detail route, which compared the raw
status string after loading the record — a working check written outside the
rule it was enforcing.

This module deliberately imports nothing from the review service. The
repository needs the *rule*, and depending on the state machine to get it would
be a cycle for the sake of one string. Keeping the predicate here means the
boundary is readable in one screen and testable without a session.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import InstrumentedAttribute

from database.models.scholarship import Scholarship

# The one published state. `ReviewStatus.APPROVED` is defined as this value so
# the state machine and the read path cannot disagree.
PUBLISHED_STATE = "approved"


def published_filter():
    """SQLAlchemy criterion for "visible to users".

    Applied by every read path a user can reach:

        repository.get_all_approved      public list dataset / matching
        repository.search_approved      public search
        repository.get_published_by_id  public detail
        repository.get_currently_active freshness-restricted reads

    Reads that legitimately need unpublished records — the review queue,
    acquisition, curation tooling — must not use it. Adding a new public query
    without this filter is the one mistake this module cannot prevent, so the
    tests assert each read path uses it.
    """
    return Scholarship.extraction_status == PUBLISHED_STATE


def is_published(scholarship) -> bool:
    """Whether one loaded record is public.

    For code that already holds a Scholarship (mapping, review tooling) and
    must not re-query. Takes the attribute from `extraction_status` only, so a
    detached instance still works.
    """
    return getattr(scholarship, "extraction_status", None) == PUBLISHED_STATE


def not_expired_filter():
    """Exclude records whose deadline has passed.

    Separate from publication on purpose: a record can be correctly published
    and correctly expired. These are two independent facts, and collapsing
    them would mean a curation decision could expire silently.
    """
    return sa.or_(
        Scholarship.deadline_state.is_(None),
        Scholarship.deadline_state != "expired",
    )


def public_filter() -> InstrumentedAttribute | sa.sql.elements.BooleanClauseList:
    """Published *and* not expired: the full public-API gate."""
    return sa.and_(published_filter(), not_expired_filter())
