"""Add historical market cap, relative strength, and KRX cache tables.

Revision ID: 20260920_05
Revises: 20260920_04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260920_05"
down_revision = "20260920_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_stock_collection_job_resource", "stock_collection_job", type_="check")
    op.create_check_constraint(
        "ck_stock_collection_job_resource",
        "stock_collection_job",
        "resource IN ('snapshot','prices','income','eps','stability','quarter_income','quarter_ratios','history_cap','history_rs')",
    )
    op.create_table(
        "stock_period_market",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("market_cap", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("cap_as_of", sa.Date(), nullable=True),
        sa.Column("cap_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rs", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("rs_as_of", sa.Date(), nullable=True),
        sa.Column("rs_base_date", sa.Date(), nullable=True),
        sa.Column("rs_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_period_market_stock_code_stock"
        ),
        sa.PrimaryKeyConstraint("stock_code", "period_end", name="pk_stock_period_market"),
    )
    op.create_table(
        "krx_historical_cache",
        sa.Column("market", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("rows", postgresql.JSONB(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('stock','index')", name="ck_krx_historical_cache_kind"),
        sa.PrimaryKeyConstraint(
            "market", "kind", "trade_date", name="pk_krx_historical_cache"
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM stock_collection_job WHERE resource IN ('history_cap', 'history_rs')"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM stock_collection_state WHERE resource IN ('history_cap', 'history_rs')"
        )
    )
    op.drop_table("krx_historical_cache")
    op.drop_table("stock_period_market")
    op.drop_constraint("ck_stock_collection_job_resource", "stock_collection_job", type_="check")
    op.create_check_constraint(
        "ck_stock_collection_job_resource",
        "stock_collection_job",
        "resource IN ('snapshot','prices','income','eps','stability','quarter_income','quarter_ratios')",
    )
