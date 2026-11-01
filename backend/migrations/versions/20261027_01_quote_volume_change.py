"""Add volume_change to stock_quote_snapshot.

Revision ID: 20261027_01
Revises: 20261005_01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20261027_01'
down_revision: str | Sequence[str] | None = '20261005_01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_quote_snapshot',
        sa.Column('volume_change', sa.Numeric(precision=24, scale=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('stock_quote_snapshot', 'volume_change')
