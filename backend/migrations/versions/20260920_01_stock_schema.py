"""Create the seven stock data tables.

Revision ID: 20260920_01
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_01"
down_revision = "99dbfe02fd98"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock",
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("market", sa.String(length=10), nullable=False),
        sa.Column("listing_status", sa.String(length=10), nullable=False),
        sa.Column("listed_at", sa.Date(), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("market IN ('KOSPI','KOSDAQ')", name="ck_stock_market"),
        sa.CheckConstraint(
            "listing_status IN ('listed','inactive')", name="ck_stock_listing_status"
        ),
        sa.PrimaryKeyConstraint("code", name="pk_stock"),
    )

    op.create_table(
        "stock_quote_snapshot",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("price", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("change", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("change_amount", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("trading_value", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("market_cap", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("source_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "price > 0 AND volume >= 0 AND trading_value >= 0 AND market_cap >= 0",
            name="ck_stock_quote_snapshot_values",
        ),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_quote_snapshot_stock"
        ),
        sa.PrimaryKeyConstraint("stock_code", name="pk_stock_quote_snapshot"),
    )

    op.create_table(
        "stock_metric_snapshot",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("per", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("pbr", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("eps", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("bps", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("foreign_ownership", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("week52_high", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("week52_low", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("source_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "foreign_ownership IS NULL OR foreign_ownership BETWEEN 0 AND 100",
            name="ck_stock_metric_snapshot_foreign_ownership",
        ),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_metric_snapshot_stock"
        ),
        sa.PrimaryKeyConstraint("stock_code", name="pk_stock_metric_snapshot"),
    )

    op.create_table(
        "stock_daily_price",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("adjustment_type", sa.String(length=12), nullable=False),
        sa.Column("open", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("high", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("low", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("close", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("adjustment_type = 'raw'", name="ck_stock_daily_price_adjustment"),
        sa.CheckConstraint(
            "volume >= 0 AND low >= 0 AND high >= low AND open >= low AND open <= high "
            "AND close >= low AND close <= high",
            name="ck_stock_daily_price_values",
        ),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_daily_price_stock"
        ),
        sa.PrimaryKeyConstraint(
            "stock_code", "trade_date", "adjustment_type", name="pk_stock_daily_price"
        ),
    )

    op.create_table(
        "stock_collection_state",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("resource", sa.String(length=16), nullable=False),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_collection_state_stock"
        ),
        sa.PrimaryKeyConstraint("stock_code", "resource", name="pk_stock_collection_state"),
    )

    op.create_table(
        "stock_collection_job",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("resource", sa.String(length=16), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=False),
        sa.Column("range_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','idle','failed')", name="ck_stock_collection_job_status"
        ),
        sa.CheckConstraint(
            "resource IN ('snapshot','prices')", name="ck_stock_collection_job_resource"
        ),
        sa.CheckConstraint(
            "range_end >= range_start AND attempts >= 0",
            name="ck_stock_collection_job_range_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_collection_job_stock"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_collection_job"),
        sa.UniqueConstraint(
            "stock_code",
            "resource",
            "range_start",
            "range_end",
            name="uq_stock_job_range",
        ),
    )
    op.create_index(
        "ix_stock_job_claim",
        "stock_collection_job",
        ["status", "next_run_at", "priority"],
    )

    op.create_table(
        "stock_data_coverage",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("adjustment_type", sa.String(length=12), nullable=False),
        sa.Column("range_start", sa.Date(), nullable=False),
        sa.Column("range_end", sa.Date(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("range_end >= range_start", name="ck_stock_data_coverage_range"),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_data_coverage_stock"
        ),
        sa.PrimaryKeyConstraint(
            "stock_code",
            "adjustment_type",
            "range_start",
            "range_end",
            name="pk_stock_data_coverage",
        ),
    )


def downgrade() -> None:
    op.drop_table("stock_data_coverage")
    op.drop_index("ix_stock_job_claim", table_name="stock_collection_job")
    op.drop_table("stock_collection_job")
    op.drop_table("stock_collection_state")
    op.drop_table("stock_daily_price")
    op.drop_table("stock_metric_snapshot")
    op.drop_table("stock_quote_snapshot")
    op.drop_table("stock")
