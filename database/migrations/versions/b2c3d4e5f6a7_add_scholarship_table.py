"""add_scholarship_table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('scholarship',
    sa.Column('scholarship_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('scholarship_name', sa.String(length=512), nullable=False),
    sa.Column('degree', sa.String(length=50), nullable=False),
    sa.Column('funding_type', sa.String(length=50), nullable=False),
    sa.Column('field_of_study', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('application_url', sa.String(length=2048), nullable=True),
    sa.Column('official_page_url', sa.String(length=2048), nullable=False),
    sa.Column('application_open', sa.Date(), nullable=True),
    sa.Column('application_deadline', sa.Date(), nullable=True),
    sa.Column('application_cycle', sa.String(length=32), nullable=True),
    sa.Column('provider_id', sa.UUID(), nullable=False),
    sa.Column('country_id', sa.UUID(), nullable=False),
    sa.Column('university_id', sa.UUID(), nullable=True),
    sa.Column('source_id', sa.UUID(), nullable=False),
    sa.Column('extraction_status', sa.String(length=50), server_default=sa.text("'pending_review'"), nullable=False),
    sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['provider_id'], ['provider.provider_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['country_id'], ['country.country_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['university_id'], ['university.university_id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['source_id'], ['source_registry.source_id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('scholarship_id')
    )
    op.create_index('ix_scholarship_name', 'scholarship', ['scholarship_name'])
    op.create_index('ix_scholarship_provider_id', 'scholarship', ['provider_id'])
    op.create_index('ix_scholarship_country_id', 'scholarship', ['country_id'])
    op.create_index('ix_scholarship_degree', 'scholarship', ['degree'])
    op.create_index('ix_scholarship_funding_type', 'scholarship', ['funding_type'])
    op.create_index('ix_scholarship_deadline', 'scholarship', ['application_deadline'])
    op.create_index('ix_scholarship_cycle', 'scholarship', ['application_cycle'])
    op.create_index('ix_scholarship_extraction_status', 'scholarship', ['extraction_status'])
    op.create_index('ix_scholarship_provider_cycle', 'scholarship', ['provider_id', 'application_cycle'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_scholarship_provider_cycle', table_name='scholarship')
    op.drop_index('ix_scholarship_extraction_status', table_name='scholarship')
    op.drop_index('ix_scholarship_cycle', table_name='scholarship')
    op.drop_index('ix_scholarship_deadline', table_name='scholarship')
    op.drop_index('ix_scholarship_funding_type', table_name='scholarship')
    op.drop_index('ix_scholarship_degree', table_name='scholarship')
    op.drop_index('ix_scholarship_country_id', table_name='scholarship')
    op.drop_index('ix_scholarship_provider_id', table_name='scholarship')
    op.drop_index('ix_scholarship_name', table_name='scholarship')
    op.drop_table('scholarship')
