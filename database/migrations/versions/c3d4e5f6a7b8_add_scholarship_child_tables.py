"""add_scholarship_child_tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-12 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create scholarship_requirement
    op.create_table(
        "scholarship_requirement",
        sa.Column("requirement_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("scholarship_id", sa.UUID(), nullable=False),
        sa.Column("minimum_gpa", sa.Float(), nullable=True),
        sa.Column("ielts_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("minimum_ielts", sa.Float(), nullable=True),
        sa.Column("toefl_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("minimum_toefl", sa.Integer(), nullable=True),
        sa.Column("gre_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("age_limit", sa.Integer(), nullable=True),
        sa.Column("work_experience", sa.String(length=20), nullable=True),
        sa.Column("research_experience", sa.String(length=20), nullable=True),
        sa.Column("publication", sa.String(length=20), nullable=True),
        sa.Column("recommendation_letter", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("motivation_letter", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cv_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("passport_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["scholarship_id"], ["scholarship.scholarship_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("requirement_id"),
        sa.UniqueConstraint("scholarship_id"),
    )

    # 2. Create scholarship_benefit
    op.create_table(
        "scholarship_benefit",
        sa.Column("benefit_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("scholarship_id", sa.UUID(), nullable=False),
        sa.Column("tuition_fee", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("monthly_allowance", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("accommodation", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("health_insurance", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("travel_ticket", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("research_grant", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["scholarship_id"], ["scholarship.scholarship_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("benefit_id"),
        sa.UniqueConstraint("scholarship_id"),
    )

    # 3. Create scholarship_timeline
    op.create_table(
        "scholarship_timeline",
        sa.Column("timeline_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("scholarship_id", sa.UUID(), nullable=False),
        sa.Column("application_open", sa.Date(), nullable=True),
        sa.Column("application_deadline", sa.Date(), nullable=True),
        sa.Column("application_cycle", sa.String(length=32), nullable=True),
        sa.Column("interview_date", sa.Date(), nullable=True),
        sa.Column("result_date", sa.Date(), nullable=True),
        sa.Column("study_start", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(["scholarship_id"], ["scholarship.scholarship_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("timeline_id"),
        sa.UniqueConstraint("scholarship_id"),
    )
    op.create_index("ix_scholarship_timeline_deadline", "scholarship_timeline", ["application_deadline"])
    op.create_index("ix_scholarship_timeline_cycle", "scholarship_timeline", ["application_cycle"])

    # 4. Create scholarship_version
    op.create_table(
        "scholarship_version",
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("scholarship_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["scholarship_id"], ["scholarship.scholarship_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("version_id"),
    )
    op.create_index("ix_scholarship_version_scholarship_id", "scholarship_version", ["scholarship_id"])

    # 5. Migrate existing timeline data from scholarship to scholarship_timeline
    op.execute("""
        INSERT INTO scholarship_timeline (
            timeline_id, scholarship_id, application_open,
            application_deadline, application_cycle, created_at, updated_at
        )
        SELECT
            gen_random_uuid(), scholarship_id, application_open,
            application_deadline, application_cycle, now(), now()
        FROM scholarship
        WHERE application_open IS NOT NULL
           OR application_deadline IS NOT NULL
           OR application_cycle IS NOT NULL
    """)

    # 6. Drop old indexes from scholarship
    op.drop_index("ix_scholarship_provider_cycle", table_name="scholarship")
    op.drop_index("ix_scholarship_cycle", table_name="scholarship")
    op.drop_index("ix_scholarship_deadline", table_name="scholarship")

    # 7. Drop old columns from scholarship
    op.drop_column("scholarship", "application_open")
    op.drop_column("scholarship", "application_deadline")
    op.drop_column("scholarship", "application_cycle")


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Re-add columns to scholarship
    op.add_column("scholarship", sa.Column("application_open", sa.Date(), nullable=True))
    op.add_column("scholarship", sa.Column("application_deadline", sa.Date(), nullable=True))
    op.add_column("scholarship", sa.Column("application_cycle", sa.String(length=32), nullable=True))

    # 2. Migrate data back from scholarship_timeline to scholarship
    op.execute("""
        UPDATE scholarship
        SET application_open = st.application_open,
            application_deadline = st.application_deadline,
            application_cycle = st.application_cycle
        FROM scholarship_timeline st
        WHERE scholarship.scholarship_id = st.scholarship_id
    """)

    # 3. Re-create old indexes
    op.create_index("ix_scholarship_deadline", "scholarship", ["application_deadline"])
    op.create_index("ix_scholarship_cycle", "scholarship", ["application_cycle"])
    op.create_index("ix_scholarship_provider_cycle", "scholarship", ["provider_id", "application_cycle"])

    # 4. Drop child tables
    op.drop_index("ix_scholarship_version_scholarship_id", table_name="scholarship_version")
    op.drop_table("scholarship_version")
    op.drop_index("ix_scholarship_timeline_cycle", table_name="scholarship_timeline")
    op.drop_index("ix_scholarship_timeline_deadline", table_name="scholarship_timeline")
    op.drop_table("scholarship_timeline")
    op.drop_table("scholarship_benefit")
    op.drop_table("scholarship_requirement")
