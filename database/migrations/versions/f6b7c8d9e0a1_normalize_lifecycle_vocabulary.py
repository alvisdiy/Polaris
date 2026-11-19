"""normalize lifecycle vocabulary

The same columns were written in two spellings and read in a third:
``source_registry.status`` was seeded as ``active`` while every discovery
query filtered ``"Active"``/``"Provisional"``, and providers were created as
``unverified`` while the per-country orchestrators filtered
``discovered``/``candidate``/``verified``. Seeded sources were therefore
invisible to discovery.

This migration makes the stored values canonical. It is data-only: no column
changes shape, so it is safe to run on a populated database.

Revision ID: f6b7c8d9e0a1
Revises: e7f8a9b0c1d2
"""

from __future__ import annotations

from alembic import op

revision = "f6b7c8d9e0a1"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE source_registry SET status = 'Active' "
        "WHERE lower(status) = 'active'"
    )
    op.execute(
        "UPDATE source_registry SET status = 'Provisional' "
        "WHERE lower(status) = 'provisional'"
    )
    op.execute(
        "UPDATE provider SET verification_status = 'discovered' "
        "WHERE verification_status = 'unverified'"
    )


def downgrade() -> None:
    # Deliberately a no-op. Reverting to the old spellings would make every
    # seeded source invisible to discovery again; the canonical values are
    # compatible with the code that reads them, so there is nothing to restore.
    pass
