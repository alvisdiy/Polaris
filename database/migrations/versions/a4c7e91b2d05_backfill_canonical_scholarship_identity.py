"""backfill canonical scholarship identity

Revision ID: a4c7e91b2d05
Revises: d5e6f7a8b9c0
Create Date: 2026-10-04

Fills in ``scholarship.identity_key`` for every row that has none, using the
canonical form in ``services.scholarship.identity``.

The earlier backfill (``e1a2b3c4d5f6``) derived keys from a weaker
normalisation — lowercase plus whitespace collapse — so two spellings of one
scholarship produced two different keys, and it resolved the resulting
collision by **deleting** the losing row. This migration does neither:

* a collision leaves the row's key NULL and is reported, because choosing a
  survivor is a curation decision, not a schema one;
* no row is deleted, updated in place, or otherwise mutated beyond its key.

A row left NULL stays outside the partial unique index and therefore outside
deduplication — visible and auditable rather than silently merged.

Downgrade recomputes the previous weak key for every row this migration
touched, so the pre-migration state is restorable.

Note on coupling: this imports the canonicaliser rather than freezing a copy
of it. That is deliberate — a frozen copy would drift from the code that
computes every new key, and the database would hold two conventions at once.
``tests/integration/test_identity_backfill.py`` pins the canonical form so a
change to it fails a test rather than silently changing what this migration
means.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4c7e91b2d05"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS = "scholarship_id, scholarship_name, provider_id, country_id, identity_key"


def _legacy_key(name, provider_id, country_id) -> str:
    """The normalisation ``e1a2b3c4d5f6`` used, for the downgrade path."""
    import hashlib
    import re

    normalized = re.sub(r"\s+", " ", (name or "").strip().lower())
    return hashlib.sha256(f"{provider_id}|{normalized}|{country_id}".encode("utf-8")).hexdigest()


def upgrade() -> None:
    from services.scholarship.identity import IdentityUnavailable, scholarship_identity_key

    conn = op.get_bind()

    taken = {
        key
        for (key,) in conn.execute(
            sa.text("SELECT DISTINCT identity_key FROM scholarship WHERE identity_key IS NOT NULL")
        ).fetchall()
    }

    rows = conn.execute(
        sa.text(f"SELECT {_COLUMNS} FROM scholarship WHERE identity_key IS NULL ORDER BY created_at")
    ).fetchall()

    filled = 0
    # Reported, not raised: a collision means two rows describe one
    # scholarship, and only a reviewer can say which row survives.
    conflicts: list[tuple[str, str]] = []

    for scholarship_id, name, provider_id, country_id, _ in rows:
        try:
            key = scholarship_identity_key(provider_id, name, country_id)
        except IdentityUnavailable:
            continue  # stays NULL and therefore visible as un-deduplicated
        if key in taken:
            conflicts.append((str(scholarship_id), key[:12]))
            continue
        taken.add(key)
        conn.execute(
            sa.text("UPDATE scholarship SET identity_key = :k WHERE scholarship_id = :id"),
            {"k": key, "id": str(scholarship_id)},
        )
        filled += 1

    if conflicts:
        print(
            f"[identity backfill] {len(conflicts)} row(s) already owned by another "
            f"identity and left NULL for review: {conflicts}"
        )
    print(f"[identity backfill] {filled} row(s) given a canonical identity_key")


def downgrade() -> None:
    from services.scholarship.identity import scholarship_identity_key

    conn = op.get_bind()

    rows = conn.execute(
        sa.text(f"SELECT {_COLUMNS} FROM scholarship WHERE identity_key IS NOT NULL")
    ).fetchall()

    taken: set[str] = set()
    restored = 0
    for scholarship_id, name, provider_id, country_id, current_key in rows:
        try:
            canonical = scholarship_identity_key(provider_id, name, country_id)
        except Exception:
            continue
        if current_key != canonical:
            continue  # written by an earlier migration; leave it alone
        legacy = _legacy_key(name, provider_id, country_id)
        if legacy in taken:
            conn.execute(
                sa.text("UPDATE scholarship SET identity_key = NULL WHERE scholarship_id = :id"),
                {"id": str(scholarship_id)},
            )
        else:
            taken.add(legacy)
            conn.execute(
                sa.text("UPDATE scholarship SET identity_key = :k WHERE scholarship_id = :id"),
                {"k": legacy, "id": str(scholarship_id)},
            )
            restored += 1

    print(f"[identity backfill downgrade] {restored} row(s) restored to the legacy key")
