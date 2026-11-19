"""m9.1 controlled vocabulary: degree and funding_type checks

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-02

Adds CHECK constraints for the two categorical scholarship fields that the
matching engine consumes as categories:

    degree         CHECK (degree IS NULL OR degree IN (5 canonical levels))
    funding_type   CHECK (funding_type IS NULL OR funding_type IN (3 types))

Phase 4 established a single vocabulary in services/domain/vocabulary.py. This
migration is the database half of that promise: without it the database would
still accept a value the application claims is impossible, and a writer that
bypasses ReviewService — a script, a psql session, a future service — would
silently produce data no profile can match.

Two different treatments, deliberately
--------------------------------------
funding_type is added VALIDATED. Every existing row already conforms (the data
holds only 'Fully Funded' and 'Partial Funded'), so the constraint can be
enforced against the whole table and prove it.

degree is added NOT VALIDATED. One approved row — e2a5bfd4, the Singapore PFP
record — carries degree='Polytechnic', published before Phase 4 existed.
Validating would fail, and the only way to make it pass would be to rewrite
that published value inside a migration. Doing so would mutate public data
outside the review boundary that Phase 2 exists to protect, and would destroy
the evidence of how the record got that way.

NOT VALID still enforces every future INSERT and UPDATE immediately; it only
declines to re-examine rows written before the constraint existed. The
grandfathered row is reported below and queued for reviewer correction, which
is the only legitimate way to change a published value.

The constraint is generated from services/domain/vocabulary.py rather than
typed out here, so the list cannot drift between the migration and the code
that enforces it at runtime. The migration imports from application code on
purpose: the vocabulary is a domain fact, and a migration is just one more
place that has to agree with it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from services.domain.vocabulary import DEGREE_LEVELS, FUNDING_TYPES

# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEGREE_CONSTRAINT = "ck_scholarship_degree_vocabulary"
FUNDING_CONSTRAINT = "ck_scholarship_funding_type_vocabulary"


def _constraint_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}
        ).first()
    )


def _check_sql(values: tuple[str, ...]) -> str:
    """Build the CHECK expression, quoting from the canonical vocabulary."""
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"degree IS NULL OR degree IN ({allowed})"


def _check_sql_funding(values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"funding_type IS NULL OR funding_type IN ({allowed})"


def _add_check(name: str, expression: str, *, not_valid: bool = False) -> None:
    """Add a CHECK constraint via explicit SQL.

    Alembic's ``create_check_constraint`` does not emit ``NOT VALID`` — it
    validates the whole table regardless, which is precisely the behaviour this
    migration must avoid for ``degree``. Emitting the statement directly keeps
    the grandfathering intent intact.
    """
    suffix = " NOT VALID" if not_valid else ""
    op.execute(
        f"ALTER TABLE scholarship ADD CONSTRAINT {name} "
        f"CHECK ({expression}){suffix}"
    )


def _out_of_vocabulary(conn, column: str, values: tuple[str, ...]):
    allowed = ", ".join(f"'{value}'" for value in values)
    return conn.execute(
        sa.text(
            f"SELECT scholarship_id, {column} FROM scholarship "
            f"WHERE {column} IS NOT NULL AND {column} NOT IN ({allowed})"
        )
    ).fetchall()


def upgrade() -> None:
    conn = op.get_bind()

    if not _constraint_exists(conn, FUNDING_CONSTRAINT):
        # Validated: the data already conforms, so prove it rather than assume.
        _add_check(FUNDING_CONSTRAINT, _check_sql_funding(FUNDING_TYPES))

    if not _constraint_exists(conn, DEGREE_CONSTRAINT):
        offenders = _out_of_vocabulary(conn, "degree", DEGREE_LEVELS)
        if offenders:
            # Reported, never repaired. Rewriting published data here would
            # break the publication boundary and erase the evidence.
            detail = ", ".join(f"{row[0]}={row[1]!r}" for row in offenders[:10])
            print(
                "\n[polaris] degree vocabulary constraint added NOT VALID.\n"
                f"[polaris] {len(offenders)} existing row(s) predate it and are "
                "grandfathered; they need reviewer correction:\n"
                f"[polaris]   {detail}\n"
                "[polaris] New and updated rows are enforced immediately.\n"
            )
            _add_check(
                DEGREE_CONSTRAINT, _check_sql(DEGREE_LEVELS), not_valid=True
            )
        else:
            _add_check(DEGREE_CONSTRAINT, _check_sql(DEGREE_LEVELS))


def downgrade() -> None:
    conn = op.get_bind()
    for name in (DEGREE_CONSTRAINT, FUNDING_CONSTRAINT):
        if _constraint_exists(conn, name):
            op.drop_constraint(name, "scholarship", type_="check")
