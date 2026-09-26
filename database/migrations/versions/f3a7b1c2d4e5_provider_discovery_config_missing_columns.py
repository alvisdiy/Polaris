"""provider discovery config missing columns

Revision ID: f3a7b1c2d4e5
Revises: e1a2b3c4d5f6
Create Date: 2026-09-24

`provider_discovery_config` drifted away from its model:

- `d7e8f9a0b1c2` creates the table without `exclude_patterns`,
  `custom_settings`, `organization_type` and `max_urls_per_source`, so a
  database built from migrations alone never has them.
- Shared development databases were built by `Base.metadata.create_all()`
  instead, which produced `exclude_patterns` and `custom_settings` (they were
  added to the model earlier) but cannot add `organization_type` or
  `max_urls_per_source` to a table that already exists.

This migration converges both paths, so the table matches the model whichever
route it was created by. Guards keep it re-runnable; every added column is
nullable or carries a server default, so existing rows stay valid.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3a7b1c2d4e5"
down_revision: Union[str, Sequence[str], None] = "e1a2b3c4d5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).first()
    )


def upgrade() -> None:
    conn = op.get_bind()
    table = "provider_discovery_config"

    if not _column_exists(conn, table, "exclude_patterns"):
        op.add_column(table, sa.Column("exclude_patterns", postgresql.JSONB(), nullable=True))
    if not _column_exists(conn, table, "organization_type"):
        op.add_column(
            table,
            sa.Column(
                "organization_type",
                sa.String(length=50),
                nullable=False,
                server_default="University",
            ),
        )
    if not _column_exists(conn, table, "max_urls_per_source"):
        op.add_column(
            table,
            sa.Column(
                "max_urls_per_source",
                sa.Integer(),
                nullable=False,
                server_default="50",
            ),
        )
    if not _column_exists(conn, table, "custom_settings"):
        op.add_column(table, sa.Column("custom_settings", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    table = "provider_discovery_config"

    for column in ("custom_settings", "max_urls_per_source", "organization_type", "exclude_patterns"):
        if _column_exists(conn, table, column):
            op.drop_column(table, column)
