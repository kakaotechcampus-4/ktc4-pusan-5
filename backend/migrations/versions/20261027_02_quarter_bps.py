"""Add bps to stock_quarterly_ratio.

Revision ID: 20261027_02
Revises: 20261027_01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '20261027_02'
down_revision: str | Sequence[str] | None = '20261027_01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_quarterly_ratio',
        sa.Column('bps', sa.Numeric(precision=24, scale=8), nullable=True),
    )
    # 기존 캐시는 bps 가 비어 있다. 24시간 TTL 을 기다리지 않고 다음 조회 때 다시 받게 한다.
    op.execute(
        sa.text(
            "UPDATE stock_collection_state SET last_success_at = NULL "
            "WHERE resource = 'quarter_ratios'"
        )
    )


def downgrade() -> None:
    op.drop_column('stock_quarterly_ratio', 'bps')
