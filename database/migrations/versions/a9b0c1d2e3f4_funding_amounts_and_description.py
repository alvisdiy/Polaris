"""funding amount as stated, plus a source description excerpt

Revision ID: a9b0c1d2e3f4
Revises: d4e5f6a7b8c9
Create Date: 2026-11-26

Until now a record could only say *what kind* of funding it had
(``funding_type``, a controlled vocabulary). It could not say how much,
in which currency, or for what period, and it carried no description at
all, so a student comparing two "Fully Funded" awards had nothing to
compare.

Semantics A (decided 2026-11-26): the amount is stored exactly as the
official page states it, with the currency and the period the page
itself uses. No FX conversion and no period conversion, because both
publish a number the source never gave. NULL means unstated: a tuition
waiver keeps ``funding_amount`` NULL (never 0, which would read as
"worth nothing"), and ``description`` is an excerpt of the official
page, never copy written at Polaris.

The columns and their CHECK constraints land in this one migration,
following the lesson of ``e7f8a9b0c1d2``: the vocabulary tuple in
``services.domain.vocabulary`` and the database constraint must change
together, or the application resolves real wording to a value the
database then refuses. The period list is read from the vocabulary
rather than typed out here, for the same reason.

Downgrade drops the columns, which discards any amounts and
descriptions stored under them. That is the honest shape of a schema
downgrade here: the data has nowhere else to live.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from services.domain.vocabulary import FUNDING_PERIODS

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERIOD_CONSTRAINT = "ck_scholarship_funding_period_vocabulary"
CURRENCY_CONSTRAINT = "ck_scholarship_funding_currency_iso"
AMOUNT_CONSTRAINT = "ck_scholarship_funding_amount_nonnegative"
DURATION_CONSTRAINT = "ck_scholarship_funding_duration_positive"

COLUMNS = (
    "funding_amount",
    "funding_currency",
    "funding_period",
    "funding_duration_months",
    "description",
)
CONSTRAINTS = (PERIOD_CONSTRAINT, CURRENCY_CONSTRAINT, AMOUNT_CONSTRAINT, DURATION_CONSTRAINT)


def _column_exists(conn, column: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'scholarship' AND column_name = :c"
        ),
        {"c": column},
    ).first()
    return row is not None


def _constraint_exists(conn, name: str) -> bool:
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n "
            "AND conrelid = 'scholarship'::regclass"
        ),
        {"n": name},
    ).first()
    return row is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "funding_amount"):
        op.add_column(
            "scholarship",
            sa.Column("funding_amount", sa.Numeric(14, 2), nullable=True,
                      comment="Cash figure exactly as stated by the source; NULL when unstated"),
        )
    if not _column_exists(conn, "funding_currency"):
        op.add_column(
            "scholarship",
            sa.Column("funding_currency", sa.String(3), nullable=True,
                      comment="ISO 4217 code as stated (EUR, USD); NULL when unstated; never converted"),
        )
    if not _column_exists(conn, "funding_period"):
        op.add_column(
            "scholarship",
            sa.Column("funding_period", sa.String(20), nullable=True,
                      comment="Period the stated amount belongs to: total | per_year | per_month | per_semester | one_off"),
        )
    if not _column_exists(conn, "funding_duration_months"):
        op.add_column(
            "scholarship",
            sa.Column("funding_duration_months", sa.Integer(), nullable=True,
                      comment="Funding duration in months, only when the source states a duration"),
        )
    if not _column_exists(conn, "description"):
        op.add_column(
            "scholarship",
            sa.Column("description", sa.Text(), nullable=True,
                      comment="Excerpt from the official page itself; never written by a model or a person at Polaris"),
        )

    allowed = ", ".join(f"'{value}'" for value in FUNDING_PERIODS)
    if not _constraint_exists(conn, PERIOD_CONSTRAINT):
        op.execute(
            f"ALTER TABLE scholarship ADD CONSTRAINT {PERIOD_CONSTRAINT} "
            f"CHECK (funding_period IS NULL OR funding_period IN ({allowed}))"
        )
    if not _constraint_exists(conn, CURRENCY_CONSTRAINT):
        op.execute(
            f"ALTER TABLE scholarship ADD CONSTRAINT {CURRENCY_CONSTRAINT} "
            "CHECK (funding_currency IS NULL OR funding_currency ~ '^[A-Z]{3}$')"
        )
    if not _constraint_exists(conn, AMOUNT_CONSTRAINT):
        op.execute(
            f"ALTER TABLE scholarship ADD CONSTRAINT {AMOUNT_CONSTRAINT} "
            "CHECK (funding_amount IS NULL OR funding_amount >= 0)"
        )
    if not _constraint_exists(conn, DURATION_CONSTRAINT):
        op.execute(
            f"ALTER TABLE scholarship ADD CONSTRAINT {DURATION_CONSTRAINT} "
            "CHECK (funding_duration_months IS NULL OR funding_duration_months > 0)"
        )


def downgrade() -> None:
    conn = op.get_bind()
    for name in reversed(CONSTRAINTS):
        if _constraint_exists(conn, name):
            op.drop_constraint(name, "scholarship", type_="check")
    for column in reversed(COLUMNS):
        if _column_exists(conn, column):
            op.drop_column("scholarship", column)
