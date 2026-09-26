"""add_provider_discovery_tables

Revision ID: d7e8f9a0b1c2
Revises: c57af8be78ef
Create Date: 2026-09-19 09:56:08.236709

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add verification lifecycle fields to provider table
    op.add_column("provider", sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="discovered"))
    op.add_column("provider", sa.Column("discovery_source", sa.String(length=2048), nullable=True))
    op.add_column("provider", sa.Column("discovery_method", sa.String(length=50), nullable=True))
    op.add_column("provider", sa.Column("discovery_evidence", sa.JSON(), nullable=True))
    op.add_column("provider", sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("provider", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("provider", sa.Column("verified_by", sa.String(length=100), nullable=True))
    op.add_column("provider", sa.Column("rejection_reason", sa.Text(), nullable=True))

    # Create provider_discovery_config table
    op.create_table(
        "provider_discovery_config",
        sa.Column("config_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("country_id", sa.UUID(), nullable=False),
        sa.Column("discovery_surface_url", sa.String(length=2048), nullable=False),
        sa.Column("discovery_strategy", sa.String(length=50), nullable=False, server_default="link_discovery"),
        sa.Column("allowed_tlds", sa.JSON(), nullable=True),
        sa.Column("keyword_filters", sa.JSON(), nullable=True),
        sa.Column("auto_verify_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confidence_threshold", sa.Float(), nullable=False, server_default=sa.text("0.8")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["country_id"], ["country.country_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("config_id"),
        sa.UniqueConstraint("country_id", "discovery_surface_url", name="uq_country_surface_url"),
    )

    # Create provider_discovery_attempt table
    op.create_table(
        "provider_discovery_attempt",
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("country_id", sa.UUID(), nullable=False),
        sa.Column("discovery_surface_url", sa.String(length=2048), nullable=False),
        sa.Column("discovered_url", sa.String(length=2048), nullable=False),
        sa.Column("discovery_method", sa.String(length=50), nullable=False),
        sa.Column("domain_pattern_matched", sa.String(length=100), nullable=True),
        sa.Column("keywords_matched", sa.JSON(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("verification_checks", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("provider_id", sa.UUID(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["country_id"], ["country.country_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["provider.provider_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("attempt_id"),
    )

    # Create indexes for performance
    op.create_index("ix_provider_verification_status", "provider", ["verification_status"])
    op.create_index("ix_provider_country_id", "provider", ["country_id"])
    op.create_index("ix_provider_discovery_config_country_id", "provider_discovery_config", ["country_id"])
    op.create_index("ix_provider_discovery_attempt_country_id", "provider_discovery_attempt", ["country_id"])
    op.create_index("ix_provider_discovery_attempt_provider_id", "provider_discovery_attempt", ["provider_id"])
    op.create_index("ix_provider_discovery_attempt_outcome", "provider_discovery_attempt", ["outcome"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_provider_discovery_attempt_outcome", table_name="provider_discovery_attempt")
    op.drop_index("ix_provider_discovery_attempt_provider_id", table_name="provider_discovery_attempt")
    op.drop_index("ix_provider_discovery_attempt_country_id", table_name="provider_discovery_attempt")
    op.drop_index("ix_provider_discovery_config_country_id", table_name="provider_discovery_config")
    op.drop_index("ix_provider_country_id", table_name="provider")
    op.drop_index("ix_provider_verification_status", table_name="provider")
    op.drop_table("provider_discovery_attempt")
    op.drop_table("provider_discovery_config")
    op.drop_column("provider", "rejection_reason")
    op.drop_column("provider", "verified_by")
    op.drop_column("provider", "verified_at")
    op.drop_column("provider", "discovered_at")
    op.drop_column("provider", "discovery_evidence")
    op.drop_column("provider", "discovery_method")
    op.drop_column("provider", "discovery_source")
    op.drop_column("provider", "verification_status")
