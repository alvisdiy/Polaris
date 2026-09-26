"""country exploration foundation

Revision ID: e1a2b3c4d5f6
Revises: b01651cfc4c4
Create Date: 2026-09-24

Creates the Country Exploration foundation:
- exploration_run (bounded-run tracking + metrics snapshot)
- discovery_frontier (operational discovery state; the model existed but had
  no table — this migration makes it real)
- provider identity columns (identity_key, merged_into_provider_id,
  identity_confidence)
- source_registry verification columns (verification_state, confidence,
  discovered_via)
- scholarship identity_key (canonical KB dedup) + partial unique index

All operations are guarded: the test harness runs Base.metadata.create_all()
before migrations, which may already have created the new tables on shared
dev databases. Guards keep this migration correct on fresh DBs too.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e1a2b3c4d5f6"
down_revision: Union[str, Sequence[str], None] = "b01651cfc4c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
            {"n": name},
        ).first()
    )


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


def _index_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
            {"n": name},
        ).first()
    )


def upgrade() -> None:
    conn = op.get_bind()

    # --- exploration_run -------------------------------------------------
    if not _table_exists(conn, "exploration_run"):
        op.create_table(
            "exploration_run",
            sa.Column("run_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("country_id", sa.UUID(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
            sa.Column("config_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("bounds_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["country_id"], ["country.country_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("run_id"),
        )
    if not _index_exists(conn, "ix_exploration_run_country_id"):
        op.create_index("ix_exploration_run_country_id", "exploration_run", ["country_id"])

    # --- discovery_frontier ----------------------------------------------
    if not _table_exists(conn, "discovery_frontier"):
        op.create_table(
            "discovery_frontier",
            sa.Column("candidate_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("country_id", sa.UUID(), nullable=False),
            sa.Column("url", sa.String(length=2048), nullable=False),
            sa.Column("url_hash", sa.String(length=64), nullable=False),
            sa.Column("candidate_type", sa.String(length=20), nullable=False, server_default="unknown"),
            sa.Column("origin", sa.String(length=30), nullable=False),
            sa.Column("origin_query", sa.String(length=2048), nullable=True),
            sa.Column("origin_url", sa.String(length=2048), nullable=True),
            sa.Column("origin_url_hash", sa.String(length=64), nullable=True),
            sa.Column("origin_source_id", sa.UUID(), nullable=True),
            sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("state", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("outcome", postgresql.JSONB(), nullable=True),
            sa.Column("run_id", sa.UUID(), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["country_id"], ["country.country_id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["origin_source_id"], ["source_registry.source_id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["run_id"], ["exploration_run.run_id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("candidate_id"),
        )
        op.create_index("uq_frontier_country_urlhash", "discovery_frontier", ["country_id", "url_hash"], unique=True)
        op.create_index("ix_frontier_claim", "discovery_frontier", ["country_id", "state", "priority"])
        op.create_index("ix_frontier_lease", "discovery_frontier", ["state", "lease_expires_at"])
        op.create_index("ix_frontier_origin_url_hash", "discovery_frontier", ["origin_url_hash"])

    # --- provider identity ------------------------------------------------
    if not _column_exists(conn, "provider", "identity_key"):
        op.add_column("provider", sa.Column("identity_key", sa.String(length=64), nullable=True))
    if not _column_exists(conn, "provider", "merged_into_provider_id"):
        op.add_column("provider", sa.Column("merged_into_provider_id", sa.UUID(), nullable=True))
    if not _column_exists(conn, "provider", "identity_confidence"):
        op.add_column("provider", sa.Column("identity_confidence", sa.Float(), nullable=True))
    if not _index_exists(conn, "ix_provider_identity_key"):
        op.create_index("ix_provider_identity_key", "provider", ["identity_key"])

    # --- source_registry verification --------------------------------------
    if not _column_exists(conn, "source_registry", "verification_state"):
        op.add_column("source_registry", sa.Column("verification_state", sa.String(length=20), nullable=True))
    if not _column_exists(conn, "source_registry", "confidence"):
        op.add_column("source_registry", sa.Column("confidence", sa.Float(), nullable=True))
    if not _column_exists(conn, "source_registry", "discovered_via"):
        op.add_column("source_registry", sa.Column("discovered_via", postgresql.JSONB(), nullable=True))
    if not _index_exists(conn, "ix_source_verification_state"):
        op.create_index("ix_source_verification_state", "source_registry", ["verification_state"])

    # --- scholarship identity dedup ----------------------------------------
    if not _column_exists(conn, "scholarship", "identity_key"):
        op.add_column("scholarship", sa.Column("identity_key", sa.String(length=64), nullable=True))
    if not _index_exists(conn, "uq_scholarship_identity"):
        op.create_index(
            "uq_scholarship_identity",
            "scholarship",
            ["identity_key"],
            unique=True,
            postgresql_where=sa.text("identity_key IS NOT NULL"),
        )

    # Backfill identity keys for existing rows (no pgcrypto dependency).
    # Pre-existing duplicate rows (same provider+name+country) collapse onto
    # the oldest row (keep_id): later rows are deleted — they are redundant
    # Knowledge Base entries, and child tables cascade.
    if _column_exists(conn, "scholarship", "identity_key"):
        import hashlib
        import re as _re

        rows = conn.execute(
            sa.text(
                "SELECT scholarship_id, scholarship_name, provider_id, country_id "
                "FROM scholarship WHERE identity_key IS NULL ORDER BY created_at"
            )
        ).fetchall()
        seen: dict[str, str] = {}
        for scholarship_id, name, provider_id, country_id in rows:
            normalized = _re.sub(r"\s+", " ", (name or "").strip().lower())
            key = hashlib.sha256(
                f"{provider_id}|{normalized}|{country_id}".encode("utf-8")
            ).hexdigest()
            keep_id = seen.get(key)
            if keep_id is not None:
                conn.execute(
                    sa.text("DELETE FROM scholarship WHERE scholarship_id = :id"),
                    {"id": str(scholarship_id)},
                )
                continue
            seen[key] = str(scholarship_id)
            conn.execute(
                sa.text("UPDATE scholarship SET identity_key = :k WHERE scholarship_id = :id"),
                {"k": key, "id": str(scholarship_id)},
            )


def downgrade() -> None:
    op.drop_index("uq_scholarship_identity", table_name="scholarship", postgresql_where=sa.text("identity_key IS NOT NULL"))
    op.drop_column("scholarship", "identity_key")
    op.drop_index("ix_source_verification_state", table_name="source_registry")
    op.drop_column("source_registry", "discovered_via")
    op.drop_column("source_registry", "confidence")
    op.drop_column("source_registry", "verification_state")
    op.drop_index("ix_provider_identity_key", table_name="provider")
    op.drop_column("provider", "identity_confidence")
    op.drop_column("provider", "merged_into_provider_id")
    op.drop_column("provider", "identity_key")
    op.drop_index("ix_frontier_origin_url_hash", table_name="discovery_frontier")
    op.drop_index("ix_frontier_lease", table_name="discovery_frontier")
    op.drop_index("ix_frontier_claim", table_name="discovery_frontier")
    op.drop_index("uq_frontier_country_urlhash", table_name="discovery_frontier")
    op.drop_table("discovery_frontier")
    op.drop_index("ix_exploration_run_country_id", table_name="exploration_run")
    op.drop_table("exploration_run")
