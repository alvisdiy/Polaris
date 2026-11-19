"""retire the placeholder Japanese university source

The seed registry contained ``https://www.university-scholarships.jp/``, a host
that does not resolve (``getaddrinfo failed`` on every run). It was a
placeholder for "various Japanese universities", not an official portal, and a
real source should be one provider's page.

Retired rather than deleted: the row is evidence of what the seed used to
contain, and the acquisition query excludes non-active statuses.

Revision ID: b8d9e0f1a2c3
Revises: a7c8d9e0f1b2
"""

from __future__ import annotations

from alembic import op

revision = "b8d9e0f1a2c3"
down_revision = "a7c8d9e0f1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE source_registry SET status = 'Retired' "
        "WHERE official_url = 'https://www.university-scholarships.jp/'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE source_registry SET status = 'Active' "
        "WHERE official_url = 'https://www.university-scholarships.jp/'"
    )
