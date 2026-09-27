"""Add annual income and EPS trend tables.

Revision ID: 20260920_02
Revises: 20260920_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_02"
down_revision = "20260920_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_stock_collection_job_resource", "stock_collection_job", type_="check")
    op.create_check_constraint(
        "ck_stock_collection_job_resource",
        "stock_collection_job",
        "resource IN ('snapshot','prices','income','eps')",
    )

    op.create_table(
        "stock_annual_income",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("revenue", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("operating_profit", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("net_income", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_annual_income_stock_code_stock"
        ),
        sa.PrimaryKeyConstraint("stock_code", "period_end", name="pk_stock_annual_income"),
    )
    op.create_table(
        "stock_annual_eps",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("eps", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_annual_eps_stock_code_stock"
        ),
        sa.PrimaryKeyConstraint("stock_code", "period_end", name="pk_stock_annual_eps"),
    )


def downgrade() -> None:
    # Remove financial work before restoring the old resource check.
    op.execute(
        sa.text("DELETE FROM stock_collection_job WHERE resource IN ('income', 'eps')")
    )
    op.execute(
        sa.text("DELETE FROM stock_collection_state WHERE resource IN ('income', 'eps')")
    )
    op.drop_table("stock_annual_eps")
    op.drop_table("stock_annual_income")
    op.drop_constraint("ck_stock_collection_job_resource", "stock_collection_job", type_="check")
    op.create_check_constraint(
        "ck_stock_collection_job_resource",
        "stock_collection_job",
        "resource IN ('snapshot','prices')",
    )
