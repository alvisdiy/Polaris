"""trigram support for catalogue search

Search matched only the scholarship name, as a substring. A student
typing a provider ("DAAD"), a field ("computer science"), or a slightly
misspelled programme name ("fulbrigt") found nothing, although the
records were there. The repository now matches across name, provider
and field of study, with trigram similarity as a typo-tolerant
fallback — which needs the pg_trgm extension and GIN indexes to stay
fast as the catalogue grows.

Revision ID: d4e5f6a7b8c9
Revises: c9e0f1a2b3d4
"""

from __future__ import annotations

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c9e0f1a2b3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_scholarship_name_trgm "
        "ON scholarship USING gin (scholarship_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_provider_name_trgm "
        "ON provider USING gin (provider_name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_provider_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_scholarship_name_trgm")
    # The extension is left installed: other objects may come to depend
    # on it, and dropping it is a deployment decision, not a downgrade.
