"""Add watchlist_item table.

Revision ID: 20261005_01
Revises: 20260922_01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20261005_01'
down_revision: str | Sequence[str] | None = '20260922_01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('watchlist_item',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('stock_code', sa.String(length=6), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['stock_code'], ['stock.code'], name='fk_watchlist_item_stock', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_watchlist_item_user', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'stock_code', name='uq_watchlist_item_user_stock')
    )
    op.create_index(op.f('ix_watchlist_item_user_id'), 'watchlist_item', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_watchlist_item_user_id'), table_name='watchlist_item')
    op.drop_table('watchlist_item')
