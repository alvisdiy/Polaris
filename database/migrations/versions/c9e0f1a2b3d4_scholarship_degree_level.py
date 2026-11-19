"""scholarship_degree_level: the award's levels when a page states a set

``scholarship.degree`` holds one level. A national scholarship database often
publishes a set instead ("Academic level: Doctoral / Master's / Bachelor's"),
and the single column could only record that as NULL. A NULL degree is treated
as unknown by the publication gate and is invisible to degree filtering, so
those programmes could never be published and could never be found by a student
who filtered on their level.

This table adds the multi-valued case without changing the column: a record with
one level keeps writing ``degree`` and no rows here, so the single-value path is
untouched.

Revision ID: c9e0f1a2b3d4
Revises: b8d9e0f1a2c3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9e0f1a2b3d4"
down_revision = "b8d9e0f1a2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scholarship_degree_level",
        sa.Column("degree_level_id", sa.UUID(), nullable=False),
        sa.Column("scholarship_id", sa.UUID(), nullable=False),
        sa.Column("degree", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scholarship_id"],
            ["scholarship.scholarship_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("degree_level_id"),
        sa.UniqueConstraint(
            "scholarship_id", "degree", name="uq_scholarship_degree_level"
        ),
    )
    op.create_index(
        "ix_scholarship_degree_level_scholarship_id",
        "scholarship_degree_level",
        ["scholarship_id"],
    )
    op.create_index(
        "ix_scholarship_degree_level_degree",
        "scholarship_degree_level",
        ["degree"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scholarship_degree_level_degree", table_name="scholarship_degree_level"
    )
    op.drop_index(
        "ix_scholarship_degree_level_scholarship_id",
        table_name="scholarship_degree_level",
    )
    op.drop_table("scholarship_degree_level")
