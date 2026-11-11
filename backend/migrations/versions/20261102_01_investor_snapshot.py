"""Add stock_investor_snapshot and the 'investor' collection resource.

Revision ID: 20261102_01
Revises: 20261031_01
"""

import sqlalchemy as sa
from alembic import op

revision = "20261102_01"
down_revision = "20261031_01"
branch_labels = None
depends_on = None

_RESOURCES = (
    "'snapshot','prices','income','eps','stability','quarter_income','quarter_ratios',"
    "'history_cap','history_rs'"
)


def upgrade() -> None:
    op.drop_constraint("ck_stock_collection_job_resource", "stock_collection_job", type_="check")
    op.create_check_constraint(
        "ck_stock_collection_job_resource",
        "stock_collection_job",
        f"resource IN ({_RESOURCES},'investor')",
    )
    op.create_table(
        "stock_investor_snapshot",
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("institution_net_qty", sa.BigInteger(), nullable=False),
        sa.Column("institution_net_value", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("source_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["stock_code"], ["stock.code"], name="fk_stock_investor_snapshot_stock"
        ),
        sa.PrimaryKeyConstraint("stock_code", name="pk_stock_investor_snapshot"),
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM stock_collection_job WHERE resource = 'investor'"))
    op.execute(sa.text("DELETE FROM stock_collection_state WHERE resource = 'investor'"))
    op.drop_table("stock_investor_snapshot")
    op.drop_constraint("ck_stock_collection_job_resource", "stock_collection_job", type_="check")
    op.create_check_constraint(
        "ck_stock_collection_job_resource",
        "stock_collection_job",
        f"resource IN ({_RESOURCES})",
    )
