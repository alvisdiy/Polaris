"""m9.1 follow-up: reconcile the funding_type CHECK constraint with the vocabulary

Revision ID: e7f8a9b0c1d2
Revises: a4c7e91b2d05
Create Date: 2026-10-15

``d5e6f7a8b9c0`` was meant to put the whole funding vocabulary in the database.
It did not, and the way it failed is the reason this migration exists.

That migration guards both halves with::

    if not _constraint_exists(conn, FUNDING_CONSTRAINT):
        _add_check(FUNDING_CONSTRAINT, _check_sql_funding(FUNDING_TYPES))

``ck_scholarship_funding_type_vocabulary`` already existed at that point, created
earlier against the three-value vocabulary, so the guard read "a constraint with
this name is present" as "this constraint is correct" and the funding half became
a silent no-op. The degree half ran, because no degree constraint existed yet,
which is why one of the two is now right and the other is not.

Measured state after this was noticed, on a database at ``d5e6f7a8b9c0`` and
later (alembic reports head, no pending revision):

    ck_scholarship_degree_vocabulary        Bachelor, Exchange, Master, PhD,
                                           Short Course
    code DEGREE_LEVELS                      same five

    ck_scholarship_funding_type_vocabulary  Fully Funded, Partial Funded,
                                           Tuition Only
    code FUNDING_TYPES                      those three plus Tuition Waiver,
                                           Stipend Only, Living Allowance,
                                           Travel Support, Research Funding

The failure is not cosmetic. ``services/ingestion/real_extractor.py`` classifies
funding through ``FUNDING_TYPE``, so live page wording resolves to the new values:
"tuition waiver" -> ``Tuition Waiver``, "living allowance" -> ``Living Allowance``,
"travel grant" -> ``Travel Support``. Each of those is a value this database
refuses, so the write is rejected at INSERT and the record is lost — the
acquisition pipeline reports success for a document whose extraction can never be
stored. The same mismatch reaches the review boundary: a reviewer correcting
``funding_type`` to a value the application's own vocabulary offers gets an
IntegrityError instead of a save.

What this migration does
------------------------
Widens the constraint to ``services.domain.vocabulary.FUNDING_TYPES``, read from
the code rather than typed out here, for the same reason ``d5e6f7a8b9c0`` did it:
two hand-maintained lists drift, and the drift is invisible until a write fails.

It is written to be a safe no-op. If the constraint already allows exactly the
current vocabulary it reports that and changes nothing, so re-running it after a
future widening is harmless rather than an error.

Widening is the only direction it performs. A row holding a value outside the
vocabulary would mean data already in the table contradicts the code; that is a
curation decision, not a schema one, so the constraint is added NOT VALID,
the offending rows are reported, and nothing is rewritten. Rewriting published
values inside a migration would bypass the review boundary and erase the evidence
of how the row got that way — the same reasoning ``d5e6f7a8b9c0`` applied to the
grandfathered ``degree='Polytechnic'`` record.

Downgrade
---------
Restores the three-value definition, which means any row now holding a widened
value would violate it. It refuses and lists those rows instead of deleting or
rewriting them: a downgrade that silently corrupts published data would be worse
than a downgrade that stops.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from services.domain.vocabulary import FUNDING_TYPES

# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "a4c7e91b2d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FUNDING_CONSTRAINT = "ck_scholarship_funding_type_vocabulary"

# The vocabulary this constraint replaced. Kept literal rather than derived,
# because it is history: a downgrade must restore what was actually there, not
# whatever the code happens to say about funding today.
PREVIOUS_FUNDING_TYPES: tuple[str, ...] = (
    "Fully Funded",
    "Partial Funded",
    "Tuition Only",
)


def _current_allowed_values(conn) -> set[str] | None:
    """Values the existing CHECK allows, or None when the constraint is absent.

    Read from ``pg_get_constraintdef`` instead of comparing against an expected
    string: the stored expression carries PostgreSQL's own casts and parenthesising,
    so a textual comparison would report a difference on a constraint that is
    already correct and rewrite it every run.
    """
    definition = conn.execute(
        sa.text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "WHERE c.conname = :n AND c.conrelid = 'scholarship'::regclass"
        ),
        {"n": FUNDING_CONSTRAINT},
    ).scalar()
    if not definition:
        return None
    import re

    return set(re.findall(r"'([^']+)'::character varying", definition))


def _check_sql(values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"funding_type IS NULL OR funding_type IN ({allowed})"


def _out_of_vocabulary(conn, values: tuple[str, ...]):
    allowed = ", ".join(f"'{value}'" for value in values)
    return conn.execute(
        sa.text(
            "SELECT scholarship_id, funding_type FROM scholarship "
            f"WHERE funding_type IS NOT NULL AND funding_type NOT IN ({allowed})"
        )
    ).fetchall()


def _replace_check(conn, values: tuple[str, ...], *, not_valid: bool = False) -> None:
    if _current_allowed_values(conn) is not None:
        op.drop_constraint(FUNDING_CONSTRAINT, "scholarship", type_="check")
    suffix = " NOT VALID" if not_valid else ""
    op.execute(
        f"ALTER TABLE scholarship ADD CONSTRAINT {FUNDING_CONSTRAINT} "
        f"CHECK ({_check_sql(values)}){suffix}"
    )


def upgrade() -> None:
    conn = op.get_bind()

    current = _current_allowed_values(conn)
    target = set(FUNDING_TYPES)

    if current == target:
        print(
            "\n[polaris] funding_type vocabulary constraint already matches "
            "services/domain/vocabulary.py; nothing to do.\n"
        )
        return

    widening = current is not None and current.issubset(target)
    offenders = _out_of_vocabulary(conn, FUNDING_TYPES)

    if offenders:
        detail = ", ".join(f"{row[0]}={row[1]!r}" for row in offenders[:10])
        print(
            "\n[polaris] funding_type vocabulary constraint added NOT VALID.\n"
            f"[polaris] {len(offenders)} existing row(s) hold a value the "
            "vocabulary does not define; they need reviewer correction:\n"
            f"[polaris]   {detail}\n"
            "[polaris] New and updated rows are enforced immediately.\n"
        )
        _replace_check(conn, FUNDING_TYPES, not_valid=True)
        return

    direction = "widened" if widening else "reconciled"
    print(
        f"\n[polaris] funding_type vocabulary constraint {direction}: "
        f"{sorted(current) if current else 'absent'} -> {sorted(target)}\n"
        "[polaris] Every existing row already conforms, so it is added VALIDATED.\n"
    )
    _replace_check(conn, FUNDING_TYPES)


def downgrade() -> None:
    conn = op.get_bind()

    # Values this downgrade would make illegal. Checked before the drop so a
    # refusal leaves the database exactly as it was found.
    blockers = conn.execute(
        sa.text(
            "SELECT scholarship_id, funding_type FROM scholarship "
            "WHERE funding_type IS NOT NULL AND funding_type NOT IN "
            "('Fully Funded', 'Partial Funded', 'Tuition Only')"
        )
    ).fetchall()
    if blockers:
        detail = ", ".join(f"{row[0]}={row[1]!r}" for row in blockers[:10])
        raise RuntimeError(
            "Refusing to narrow funding_type to the previous vocabulary: "
            f"{len(blockers)} row(s) use a value it does not allow ({detail}). "
            "Correct those rows through the review boundary first, or leave the "
            "constraint widened."
        )

    if _current_allowed_values(conn) is None:
        return
    _replace_check(conn, PREVIOUS_FUNDING_TYPES)
