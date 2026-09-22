"""Add annual EPS health fields and stability trends.

Revision ID: 20260920_03
Revises: 20260920_02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260920_03"
down_revision = "20260920_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_stock_collection_job_resource", "stock_collection_job", type_="check")
    op.create_check_constraint(
        "ck_stock_collection_job_resource",
        "stock_collection_job",
        "resource IN ('snapshot','prices','income','eps','stability')",
    )
    op.add_column(
        "stock_annual_eps", sa.Column("roe", sa.Numeric(precision=24, scale=8), nullable=True)
    )
    op.add_column(
        "stock_annual_eps",
        sa.Column("debt_ratio", sa.Numeric(precision=24, scale=8), nullable=True),
    )
    op.create_table(
        "stock_annual_stability",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("current_ratio", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_annual_stability_stock_code_stock"
        ),
        sa.PrimaryKeyConstraint("stock_code", "period_end", name="pk_stock_annual_stability"),
    )
    op.execute(
        sa.text(
            "UPDATE stock_collection_state SET last_success_at = NULL "
            "WHERE resource = 'eps'"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM stock_collection_job WHERE resource = 'stability'"))
    op.execute(sa.text("DELETE FROM stock_collection_state WHERE resource = 'stability'"))
    op.drop_table("stock_annual_stability")
    op.drop_column("stock_annual_eps", "debt_ratio")
    op.drop_column("stock_annual_eps", "roe")
    op.drop_constraint("ck_stock_collection_job_resource", "stock_collection_job", type_="check")
    op.create_check_constraint(
        "ck_stock_collection_job_resource",
        "stock_collection_job",
        "resource IN ('snapshot','prices','income','eps')",
    )
