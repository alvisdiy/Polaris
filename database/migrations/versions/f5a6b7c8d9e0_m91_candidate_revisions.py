"""m9.1 candidate revisions (reacquisition publication boundary)

Revision ID: f5a6b7c8d9e0
Revises: d2e3f4a5b6c7
Create Date: 2026-10-02

Adds `scholarship_candidate_revision`: a child of Scholarship holding
re-acquisition proposals that have NOT been published.

Before this migration a re-acquisition of an APPROVED scholarship wrote the
freshly observed deadline/cycle straight onto the Scholarship row, bumped
`scholarship_version`, and left `extraction_status = 'approved'` and the public
API untouched. That is a silent mutation of published data: no state
transition, no review action, nothing for a reviewer to see or refuse. It was
reproduced against the live Singapore record (deadline None -> 2099-01-01,
versions 8 -> 9, review actions unchanged).

The observation now lands here instead. The Scholarship row is not written at
all until a reviewer approves the candidate, and that approval happens inside
ReviewService in one transaction.

No backfill: this is new behaviour, not a schema repair. Existing published
records are unchanged and remain exactly as approved. Any pre-existing silent
mutations are historical facts recorded in `scholarship_version`, and rewriting
them would be a worse kind of dishonesty than leaving them.

Operations are guarded because the test harness runs Base.metadata.create_all()
against shared development databases before migrations.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
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

    if not _table_exists(conn, "scholarship_candidate_revision"):
        _create_candidate_table(conn)

    # Deliberately outside the guard above: the table and this column are
    # created independently, and `create_all()` may have made either without
    # the other.
    if not _column_exists(conn, "scholarship_review_action", "candidate_id"):
        op.add_column(
            "scholarship_review_action",
            sa.Column(
                "candidate_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(
                    "scholarship_candidate_revision.candidate_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment="CandidateRevision this action decided, when it decided a proposal",
            ),
        )


def _create_candidate_table(conn) -> None:
    op.create_table(
        "scholarship_candidate_revision",
        sa.Column(
            "candidate_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "scholarship_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scholarship.scholarship_id", ondelete="CASCADE"),
            nullable=False,
            comment="The canonical scholarship this proposes changes to",
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="pending",
            comment="pending | approved | rejected | superseded",
        ),
        # SET NULL, not CASCADE: the captured page is evidence that must
        # outlive document pruning. Losing the scholarship loses the proposal
        # (CASCADE is right); losing a raw document should only detach it.
        sa.Column(
            "raw_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_document.document_id", ondelete="SET NULL"),
            nullable=True,
            comment="RawDocument this proposal was extracted from",
        ),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "origin",
            sa.String(length=32),
            nullable=True,
            comment="What produced the candidate: reacquisition (M9.1), later manual reconciles",
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "proposed_changes",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="[{field, previous, new}] - observed values not yet published",
        ),
        sa.Column(
            "field_provenance",
            postgresql.JSONB(),
            nullable=True,
            comment="Per-field evidence for the proposed values",
        ),
        sa.Column(
            "quality_snapshot",
            postgresql.JSONB(),
            nullable=True,
            comment="Publication-gate result the proposal would produce",
        ),
        sa.Column(
            "base_version_number",
            sa.Integer(),
            nullable=True,
            comment="ScholarshipVersion.version_number when this candidate was proposed",
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # One pending candidate per (scholarship, source_url) is the real
    # invariant: repeated crawls of an unchanged page must not pile up
    # duplicate proposals for a reviewer to triage.
    if not _index_exists(conn, "ix_candidate_revision_scholarship_status"):
        op.create_index(
            "ix_candidate_revision_scholarship_status",
            "scholarship_candidate_revision",
            ["scholarship_id", "status"],
        )
    if not _index_exists(conn, "uq_candidate_revision_pending_source"):
        op.create_index(
            "uq_candidate_revision_pending_source",
            "scholarship_candidate_revision",
            ["scholarship_id", "source_url"],
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "scholarship_candidate_revision"):
        return

    # The audit table references the candidate table, so the column has to go
    # first or the drop below fails on the dependent constraint.
    if _column_exists(conn, "scholarship_review_action", "candidate_id"):
        op.drop_column("scholarship_review_action", "candidate_id")

    if _index_exists(conn, "uq_candidate_revision_pending_source"):
        op.drop_index(
            "uq_candidate_revision_pending_source",
            table_name="scholarship_candidate_revision",
        )
    if _index_exists(conn, "ix_candidate_revision_scholarship_status"):
        op.drop_index(
            "ix_candidate_revision_scholarship_status",
            table_name="scholarship_candidate_revision",
        )
    op.drop_table("scholarship_candidate_revision")
