"""Add market snapshot and ranking snapshot tables.

Revision ID: 20260922_01
Revises: 20260920_05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260922_01'
down_revision: Union[str, Sequence[str], None] = '20260920_05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('market_snapshot',
    sa.Column('code', sa.String(length=24), nullable=False),
    sa.Column('value', sa.Numeric(precision=24, scale=8), nullable=True),
    sa.Column('change', sa.Numeric(precision=24, scale=8), nullable=True),
    sa.Column('observation_date', sa.Date(), nullable=True),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('ranking_snapshot',
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.PrimaryKeyConstraint('kind')
    )


def downgrade() -> None:
    op.drop_table('ranking_snapshot')
    op.drop_table('market_snapshot')