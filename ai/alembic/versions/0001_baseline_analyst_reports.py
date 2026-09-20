"""baseline: analyst_reports

alembic 을 도입하기 전에 `create_all` 로 이미 만들어져 있던 표다. 그래서 이 리비전은
**두 가지로 쓰인다.**

  - 새 DB: `alembic upgrade head` 가 이 표를 만든다
  - 쓰던 DB: 표가 이미 있으므로 `alembic stamp 0001` 로 "여기까지는 적용된 것으로
    친다" 고 도장만 찍고 넘어간다. 그 다음 `upgrade head` 가 0002 만 적용한다

둘을 한 리비전에 섞지 않으려고 새 표(0002)와 갈라 뒀다. 한 리비전에 몰아넣으면
쓰던 DB 에서는 stamp 도 upgrade 도 맞지 않게 된다 — stamp 하면 새 표가 안 생기고
upgrade 하면 analyst_reports 에서 "이미 있다" 로 터진다.

내용은 `app/models/analyst_report.py` 의 metadata 를 그대로 옮긴 것이고, 손으로
적지 않고 alembic 렌더러로 뽑았다.

Revision ID: 0001
Revises:
Create Date: 2026-09-21
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
