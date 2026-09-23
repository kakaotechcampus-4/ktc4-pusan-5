"""add stock_move_analysis tables

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

우리가 LLM 으로 생성한 종목 변동 요인 보고서 네 표를 만든다. 설계 근거는 `app/models/stock_move_analysis.py`
의 주석에 있고 여기 적지 않는다 — 같은 설명을 두 곳에 두면 한쪽만 고쳐진다.

이 리비전이 만드는 표는 backend 의 `report` / `report_block` / `report_citation` 과
이름이 겹치지 않는다. 같은 Postgres 를 쓰므로 겹치면 남의 표를 건드리게 된다.

내용은 손으로 적지 않고 alembic 렌더러로 metadata 에서 뽑았다.

Revision ID: 0019_stock_move_analysis
Revises: 0018_source_category
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_stock_move_analysis"
down_revision: str | None = "0018_source_category"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_move_analyses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=200), nullable=True),
        sa.Column("ticker", sa.String(length=6), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_pct", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("verdict", sa.String(length=24), nullable=True),
        sa.Column("summary_move", sa.Text(), nullable=True),
        sa.Column("summary_main_cause", sa.Text(), nullable=True),
        sa.Column("summary_counter", sa.Text(), nullable=True),
        sa.Column("summary_unexplained", sa.Text(), nullable=True),
        sa.Column("terms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("background", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("not_found", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parse_status", sa.String(length=20), nullable=False),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("verify_status", sa.String(length=20), nullable=False),
        sa.Column("verify_error", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 자연키 (ticker, target_date, as_of) 에 UNIQUE 를 걸지 않는다. 같은 기준시각의
    # 재생성도 새 행으로 쌓아야 해서다. 조회용 인덱스로만 둔다.
    op.create_index("ix_stock_move_analysis_ticker_as_of", "stock_move_analyses", ["ticker", "as_of"])
    op.create_index("ix_stock_move_analysis_target_date", "stock_move_analyses", ["target_date"])
    # backend 조회 전제가 verify_status = passed 다. 미검증·실패 행이 대부분일 수 있어
    # 부분 인덱스로 둔다.
    op.create_index(
        "ix_stock_move_analysis_passed",
        "stock_move_analyses",
        ["ticker", "as_of"],
        postgresql_where=sa.text("verify_status = 'passed'"),
    )

    op.create_table(
        "stock_move_analysis_factors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("stance", sa.String(length=16), nullable=True),
        sa.Column("direction_match", sa.Boolean(), nullable=True),
        sa.Column("size_fit", sa.String(length=16), nullable=True),
        sa.Column("unconfirmed", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["analysis_id"], ["stock_move_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("analysis_id", "order_index", name="uq_stock_move_analysis_factor_order"),
    )
    op.create_index(
        "ix_stock_move_analysis_factors_analysis_id", "stock_move_analysis_factors", ["analysis_id"]
    )

    op.create_table(
        "stock_move_analysis_factor_sources",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("factor_id", sa.BigInteger(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("channel", sa.String(length=128), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("datetime_kst", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("match", sa.String(length=16), nullable=True),
        sa.Column("is_market_recap", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["factor_id"], ["stock_move_analysis_factors.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("factor_id", "order_index", name="uq_stock_move_analysis_source_order"),
    )
    op.create_index(
        "ix_stock_move_analysis_factor_sources_factor_id",
        "stock_move_analysis_factor_sources",
        ["factor_id"],
    )
    op.create_index("ix_stock_move_analysis_source_url", "stock_move_analysis_factor_sources", ["url"])

    # 이번 PR 은 표만 만들고 쓰지 않는다. AI 서버(적재)와 검수 쪽이 같은 행을
    # 건드리면 단방향이 깨져서 보고서 표와 갈라 뒀다.
    op.create_table(
        "stock_move_analysis_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.BigInteger(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reviewer", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["stock_move_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stock_move_analysis_review_analysis", "stock_move_analysis_reviews", ["analysis_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_stock_move_analysis_review_analysis", table_name="stock_move_analysis_reviews")
    op.drop_table("stock_move_analysis_reviews")
    op.drop_index("ix_stock_move_analysis_source_url", table_name="stock_move_analysis_factor_sources")
    op.drop_index(
        "ix_stock_move_analysis_factor_sources_factor_id",
        table_name="stock_move_analysis_factor_sources",
    )
    op.drop_table("stock_move_analysis_factor_sources")
    op.drop_index("ix_stock_move_analysis_factors_analysis_id", table_name="stock_move_analysis_factors")
    op.drop_table("stock_move_analysis_factors")
    op.drop_index("ix_stock_move_analysis_ticker_as_of", table_name="stock_move_analyses")
    op.drop_index("ix_stock_move_analysis_target_date", table_name="stock_move_analyses")
    op.drop_index(
        "ix_stock_move_analysis_passed",
        table_name="stock_move_analyses",
        postgresql_where=sa.text("verify_status = 'passed'"),
    )
    op.drop_table("stock_move_analyses")
