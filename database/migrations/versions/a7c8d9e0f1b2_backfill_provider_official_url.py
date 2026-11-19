"""backfill provider official_url from its sources

``register_source`` created Provider rows without ``official_url``. The
coverage orchestrator correctly refuses to create a source from a provider
whose official page is unknown, so every seeded provider was skipped and a
country run reported zero sources against a database that had them.

The source row has always carried the URL; this backfills the provider from
its highest-priority source.

Revision ID: a7c8d9e0f1b2
Revises: f6b7c8d9e0a1
"""

from __future__ import annotations

from alembic import op

revision = "a7c8d9e0f1b2"
down_revision = "f6b7c8d9e0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE provider AS p
        SET official_url = s.official_url
        FROM (
            SELECT DISTINCT ON (provider_id) provider_id, official_url
            FROM source_registry
            WHERE provider_id IS NOT NULL AND official_url IS NOT NULL
            ORDER BY provider_id, priority, created_at
        ) AS s
        WHERE p.provider_id = s.provider_id
          AND p.official_url IS NULL
        """
    )


def downgrade() -> None:
    # The backfilled values are correct; clearing them would make coverage
    # skip the providers again. No-op by design.
    pass
