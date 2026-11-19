"""m9.1 atomic versioning: unique (scholarship_id, version_number)

Revision ID: c4d5e6f7a8b9
Revises: f5a6b7c8d9e0
Create Date: 2026-10-02

Adds UNIQUE (scholarship_id, version_number) to scholarship_version.

Both version writers allocated numbers with an unlocked
``MAX(version_number) + 1``: ReviewService.write_version (approve / reject /
correct / approve_candidate) and AcquisitionService._merge_reacquisition. Two
transactions that read the same MAX before either committed both computed the
same next number, and whichever flushed last would either win silently or fail
on a constraint the database did not have. Version numbers are the ordering the
audit trail is read by, so two rows claiming the same position is not a
cosmetic defect — it makes "what did this record look like after version N"
unanswerable.

The constraint is the authority. Application-level locking (SELECT ... FOR
UPDATE in ReviewService) makes the common path cheap and gives clean error
messages, but only the database can refuse a duplicate when a writer is not
ReviewService at all.

No backfill and no renumbering. The pre-flight check found zero duplicate
(scholarship_id, version_number) groups and zero numbering gaps across all 134
existing version rows, so history is contiguous and the constraint applies
cleanly. Had duplicates existed they would have been reported, not repaired:
renumbering published history to satisfy a constraint would destroy the very
record this milestone exists to protect.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "uq_scholarship_version_number"


def _index_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": name}
        ).first()
    )


def _constraint_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT 1 FROM pg_constraint WHERE conname = :n"
            ),
            {"n": name},
        ).first()
    )


def _duplicates(conn):
    """(scholarship_id, version_number) pairs appearing more than once."""
    return conn.execute(
        sa.text(
            "SELECT scholarship_id, version_number, COUNT(*) AS n "
            "FROM scholarship_version "
            "GROUP BY scholarship_id, version_number "
            "HAVING COUNT(*) > 1 "
            "ORDER BY n DESC"
        )
    ).fetchall()


def upgrade() -> None:
    conn = op.get_bind()

    # Refuse rather than repair. Publishing a constraint that silently
    # renumbered history would make the audit trail claim an ordering that
    # never happened, which is a worse failure than a blocked migration.
    duplicates = _duplicates(conn)
    if duplicates:
        detail = ", ".join(
            f"scholarship={row[0]} version={row[1]} x{row[2]}" for row in duplicates[:10]
        )
        raise RuntimeError(
            "cannot add UNIQUE(scholarship_id, version_number): existing "
            f"duplicates must be resolved by hand ({detail}). Aborting rather "
            "than renumbering published history."
        )

    if _constraint_exists(conn, CONSTRAINT_NAME):
        return

    op.create_unique_constraint(
        CONSTRAINT_NAME,
        "scholarship_version",
        ["scholarship_id", "version_number"],
    )


def downgrade() -> None:
    conn = op.get_bind()

    if _constraint_exists(conn, CONSTRAINT_NAME):
        op.drop_constraint(
            CONSTRAINT_NAME, "scholarship_version", type_="unique"
        )
    elif _index_exists(conn, CONSTRAINT_NAME):
        # create_unique_constraint also materialises an index of the same name;
        # dropping the constraint alone leaves it behind.
        op.drop_index(CONSTRAINT_NAME, table_name="scholarship_version")
