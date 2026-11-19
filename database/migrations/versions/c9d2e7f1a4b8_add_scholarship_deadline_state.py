"""add scholarship deadline_state

Revision ID: c9d2e7f1a4b8
Revises: f3a7b1c2d4e5
Create Date: 2026-09-26

Add scholarship.deadline_state — explicit freshness classification of the
application deadline (active | expired | unknown | rolling). NULL until
classified, so rows predating the column are not silently treated as current.
Kept as a plain column (not an enum) for the same reason extraction_status is:
the application layer owns the state machine.
"""
import sqlalchemy as sa
from alembic import op

revision = "c9d2e7f1a4b8"
down_revision = "f3a7b1c2d4e5"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "scholarship", "deadline_state"):
        op.add_column(
            "scholarship",
            sa.Column(
                "deadline_state",
                sa.String(length=20),
                nullable=True,
                comment="Deadline freshness: active | expired | unknown | rolling (NULL = not yet classified)",
            ),
        )
    if not _index_exists(conn, "scholarship", "ix_scholarship_deadline_state"):
        op.create_index("ix_scholarship_deadline_state", "scholarship", ["deadline_state"])


def _index_exists(conn, table: str, index: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename = :t AND indexname = :i"
        ),
        {"t": table, "i": index},
    ).first()
    return row is not None


def downgrade() -> None:
    conn = op.get_bind()
    if _index_exists(conn, "scholarship", "ix_scholarship_deadline_state"):
        op.drop_index("ix_scholarship_deadline_state", table_name="scholarship")
    if _column_exists(conn, "scholarship", "deadline_state"):
        op.drop_column("scholarship", "deadline_state")
