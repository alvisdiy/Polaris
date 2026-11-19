"""m9 review and curation foundation

Revision ID: d2e3f4a5b6c7
Revises: c9d2e7f1a4b8
Create Date: 2026-10-02

Adds the M9 production knowledge-base boundary:

- scholarship_review_action (append-only audit trail: actor, timestamp,
  previous/new state, reason, per-field changes, quality snapshot)
- scholarship curation columns (extraction_confidence, quality_report,
  conflicts, field_provenance, provenance_origin, reviewed_at/by/notes)
- source_registry acquisition-policy columns (page_type, canonical_url,
  url_hash, acquisition_state/error/attempts/at, scholarship_page_urls,
  rejection_reason) + the url_hash index that makes source identity
  independent of raw string matching across redirects

Backfill is deliberately conservative: existing rows get explicit
"unknown", never a guessed value. existing source_registry rows without a
verification_state are marked NEEDS_REVIEW so the review queue is truthful
about what has never actually been verified.

Every operation is guarded because the test harness runs
Base.metadata.create_all() before migrations on shared dev databases.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c9d2e7f1a4b8"
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
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": name}
        ).first()
    )


def upgrade() -> None:
    conn = op.get_bind()

    # --- scholarship curation columns ------------------------------------
    if not _column_exists(conn, "scholarship", "extraction_confidence"):
        op.add_column("scholarship", sa.Column("extraction_confidence", sa.Float(), nullable=True))
    if not _column_exists(conn, "scholarship", "quality_report"):
        op.add_column("scholarship", sa.Column("quality_report", postgresql.JSONB(), nullable=True))
    if not _column_exists(conn, "scholarship", "conflicts"):
        op.add_column("scholarship", sa.Column("conflicts", postgresql.JSONB(), nullable=True))
    if not _column_exists(conn, "scholarship", "field_provenance"):
        op.add_column("scholarship", sa.Column("field_provenance", postgresql.JSONB(), nullable=True))
    if not _column_exists(conn, "scholarship", "provenance_origin"):
        op.add_column("scholarship", sa.Column("provenance_origin", sa.String(length=32), nullable=True))
    if not _column_exists(conn, "scholarship", "reviewed_at"):
        op.add_column("scholarship", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    if not _column_exists(conn, "scholarship", "reviewed_by"):
        op.add_column("scholarship", sa.Column("reviewed_by", sa.String(length=128), nullable=True))
    if not _column_exists(conn, "scholarship", "review_notes"):
        op.add_column("scholarship", sa.Column("review_notes", sa.Text(), nullable=True))

    if not _index_exists(conn, "ix_scholarship_provenance_origin"):
        op.create_index("ix_scholarship_provenance_origin", "scholarship", ["provenance_origin"])
    if not _index_exists(conn, "ix_scholarship_reviewed_at"):
        op.create_index("ix_scholarship_reviewed_at", "scholarship", ["reviewed_at"])

    # Backfill: rows that entered the KB through a script get that origin
    # recorded explicitly; anything unrecognised stays NULL (= unknown).
    conn.execute(
        sa.text(
            "UPDATE scholarship SET provenance_origin = 'unknown' "
            "WHERE provenance_origin IS NULL"
        )
    )

    # --- source_registry acquisition-policy columns ---------------------
    if not _column_exists(conn, "source_registry", "page_type"):
        op.add_column("source_registry", sa.Column("page_type", sa.String(length=32), nullable=True))
    if not _column_exists(conn, "source_registry", "canonical_url"):
        op.add_column("source_registry", sa.Column("canonical_url", sa.String(length=2048), nullable=True))
    if not _column_exists(conn, "source_registry", "url_hash"):
        op.add_column("source_registry", sa.Column("url_hash", sa.String(length=64), nullable=True))
    if not _column_exists(conn, "source_registry", "acquisition_state"):
        op.add_column("source_registry", sa.Column("acquisition_state", sa.String(length=32), nullable=True))
    if not _column_exists(conn, "source_registry", "acquisition_error"):
        op.add_column("source_registry", sa.Column("acquisition_error", sa.Text(), nullable=True))
    if not _column_exists(conn, "source_registry", "acquisition_attempts"):
        op.add_column(
            "source_registry",
            sa.Column("acquisition_attempts", sa.Integer(), nullable=False, server_default="0"),
        )
    if not _column_exists(conn, "source_registry", "last_acquisition_at"):
        op.add_column("source_registry", sa.Column("last_acquisition_at", sa.DateTime(timezone=True), nullable=True))
    if not _column_exists(conn, "source_registry", "scholarship_page_urls"):
        op.add_column("source_registry", sa.Column("scholarship_page_urls", postgresql.JSONB(), nullable=True))
    if not _column_exists(conn, "source_registry", "rejection_reason"):
        op.add_column("source_registry", sa.Column("rejection_reason", sa.Text(), nullable=True))

    if not _index_exists(conn, "ix_source_registry_url_hash"):
        op.create_index("ix_source_registry_url_hash", "source_registry", ["url_hash"])

    # Canonicalize existing URLs so url_hash lookup works immediately for
    # rows registered before this migration.
    rows = conn.execute(
        sa.text("SELECT source_id, official_url FROM source_registry WHERE canonical_url IS NULL")
    ).fetchall()
    if rows:
        import hashlib
        from urllib.parse import parse_qsl, unquote, urlparse, urlunparse

        _TRACKING = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term",
            "utm_content", "gclid", "fbclid", "ref", "referrer",
        }

        def _normalize(url: str) -> str:
            url = (url or "").strip()
            if not url:
                return ""
            if not url.lower().startswith(("http://", "https://")):
                url = "https://" + url
            p = urlparse(url)
            host = p.netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            path = unquote(p.path or "")
            while "//" in path:
                path = path.replace("//", "/")
            if len(path) > 1 and path.endswith("/"):
                path = path.rstrip("/")
            params = sorted(
                (k.lower(), v)
                for k, v in parse_qsl(p.query, keep_blank_values=True)
                if k.lower() not in _TRACKING
            )
            query = "&".join(f"{k}={v}" for k, v in params)
            return urlunparse((p.scheme.lower(), host, path, "", query, ""))

        for source_id, official_url in rows:
            canonical = _normalize(official_url)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest() if canonical else None
            conn.execute(
                sa.text(
                    "UPDATE source_registry SET canonical_url = :c, url_hash = :h "
                    "WHERE source_id = :sid"
                ),
                {"c": canonical, "h": digest, "sid": source_id},
            )

    # Rows written before this migration were never put through the
    # verification engine. Marking them NEEDS_REVIEW (rather than leaving
    # NULL or assuming VERIFIED) keeps the queue honest.
    conn.execute(
        sa.text(
            "UPDATE source_registry SET verification_state = 'NEEDS_REVIEW' "
            "WHERE verification_state IS NULL"
        )
    )

    # --- review audit trail ---------------------------------------------
    if not _table_exists(conn, "scholarship_review_action"):
        op.create_table(
            "scholarship_review_action",
            sa.Column("review_action_id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "scholarship_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("action", sa.String(length=32), nullable=False),
            sa.Column("actor", sa.String(length=128), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("previous_state", sa.String(length=24), nullable=True),
            sa.Column("new_state", sa.String(length=24), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("field_changes", postgresql.JSONB(), nullable=False),
            sa.Column("evidence_url", sa.String(length=2048), nullable=True),
            sa.Column(
                "version_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("scholarship_version.version_id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("quality_snapshot", postgresql.JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_review_action_scholarship",
            "scholarship_review_action",
            ["scholarship_id", "occurred_at"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "scholarship_review_action"):
        if _index_exists(conn, "ix_review_action_scholarship"):
            op.drop_index("ix_review_action_scholarship", table_name="scholarship_review_action")
        op.drop_table("scholarship_review_action")

    if _index_exists(conn, "ix_source_registry_url_hash"):
        op.drop_index("ix_source_registry_url_hash", table_name="source_registry")
    for col in (
        "rejection_reason", "scholarship_page_urls", "last_acquisition_at",
        "acquisition_attempts", "acquisition_error", "acquisition_state",
        "url_hash", "canonical_url", "page_type",
    ):
        if _column_exists(conn, "source_registry", col):
            op.drop_column("source_registry", col)

    if _index_exists(conn, "ix_scholarship_reviewed_at"):
        op.drop_index("ix_scholarship_reviewed_at", table_name="scholarship")
    if _index_exists(conn, "ix_scholarship_provenance_origin"):
        op.drop_index("ix_scholarship_provenance_origin", table_name="scholarship")
    for col in (
        "review_notes", "reviewed_by", "reviewed_at", "provenance_origin",
        "field_provenance", "conflicts", "quality_report", "extraction_confidence",
    ):
        if _column_exists(conn, "scholarship", col):
            op.drop_column("scholarship", col)
