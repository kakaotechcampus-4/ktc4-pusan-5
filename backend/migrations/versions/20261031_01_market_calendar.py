"""Add market_calendar table.

Revision ID: 20261031_01
Revises: 20261027_02

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20261031_01'
down_revision: str | Sequence[str] | None = '20261027_02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('market_calendar',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('is_open', sa.Boolean(), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('day')
    )


def downgrade() -> None:
    op.drop_table('market_calendar')
