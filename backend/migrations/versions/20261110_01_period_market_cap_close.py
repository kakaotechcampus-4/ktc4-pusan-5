"""Add stock_period_market.cap_close so PBR no longer depends on chart candles.

Revision ID: 20261110_01
Revises: 20261102_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_01"
down_revision = "20261102_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_period_market",
        sa.Column("cap_close", sa.Numeric(precision=24, scale=8), nullable=True),
    )
    # 종가 컬럼이 생기기 전에 수집한 행은 종가가 없다. 만료로 보이게 해서 다음 조회 때
    # history_cap 이 다시 수집하도록 한다. KRX 전종목 응답은 캐시되어 있어 외부 호출은 거의 없다.
    op.execute("UPDATE stock_period_market SET cap_collected_at = NULL WHERE cap_as_of IS NOT NULL")


def downgrade() -> None:
    op.drop_column("stock_period_market", "cap_close")
