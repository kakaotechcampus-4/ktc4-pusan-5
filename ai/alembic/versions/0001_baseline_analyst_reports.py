"""Create the original analyst_reports schema.

Revision ID: 0001
Revises:

#26의 초기 스키마를 재사용한다. source_category 추가 이전 구조이며,
현재 모델을 참조하지 않는다. 기존 DB 전환 절차는 README를 참고한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyst_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("item_code", sa.String(length=6), nullable=True),
        sa.Column("item_name", sa.String(length=64), nullable=True),
        sa.Column("broker", sa.String(length=64), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("write_date", sa.Date(), nullable=False),
        sa.Column("read_count", sa.Integer(), nullable=True),
        sa.Column("opinion", sa.String(length=16), nullable=True),
        sa.Column("goal_price", sa.BigInteger(), nullable=True),
        sa.Column("price_at_write", sa.BigInteger(), nullable=True),
        sa.Column("upside_pct", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("sector_opinion", sa.String(length=16), nullable=True),
        sa.Column("top_picks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary_html", sa.Text(), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("summary_chars", sa.Integer(), nullable=True),
        sa.Column("end_url", sa.Text(), nullable=True),
        sa.Column("attach_url", sa.Text(), nullable=True),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=True),
        sa.Column("pdf_bytes", sa.BigInteger(), nullable=True),
        sa.Column("pdf_pages", sa.Integer(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_chars", sa.Integer(), nullable=True),
        sa.Column("body_status", sa.String(length=16), nullable=False),
        sa.Column("body_extractor", sa.String(length=16), nullable=True),
        sa.Column("body_error", sa.Text(), nullable=True),
        sa.Column("body_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "category", "source_id", name="uq_analyst_report_source_id"),
    )
    op.create_index(
        "ix_analyst_report_body_status", "analyst_reports", ["body_status", "write_date"]
    )
    op.create_index("ix_analyst_report_broker_date", "analyst_reports", ["broker", "write_date"])
    op.create_index("ix_analyst_report_code_date", "analyst_reports", ["item_code", "write_date"])
    op.create_index("ix_analyst_report_date", "analyst_reports", ["write_date"])
    op.create_index("ix_analyst_reports_pdf_sha256", "analyst_reports", ["pdf_sha256"])


def downgrade() -> None:
    op.drop_index("ix_analyst_reports_pdf_sha256", table_name="analyst_reports")
    op.drop_index("ix_analyst_report_date", table_name="analyst_reports")
    op.drop_index("ix_analyst_report_code_date", table_name="analyst_reports")
    op.drop_index("ix_analyst_report_broker_date", table_name="analyst_reports")
    op.drop_index("ix_analyst_report_body_status", table_name="analyst_reports")
    op.drop_table("analyst_reports")
