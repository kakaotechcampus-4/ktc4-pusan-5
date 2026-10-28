"""index source cards by stock and public time

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

종목 브리핑이 "이 종목에 관한 자료 중 기준 시각 이전에 나온 것" 을 찾을 수 있게 한다.
설계 근거는 `app/models/source_card.py`·`app/models/stock_move_analysis.py` 에 있다.

    source_card.available_at        자료가 공개돼 있었다고 확인된 가장 이른 시각
    source_card_stocks              자료 ↔ 종목 (자료 하나가 여러 종목을 다룰 수 있다)
    stock_move_analysis_factor_sources.source_card_id
                                    보고서 출처를 공통 자료 ID 로 잇는다

기존 행은 비워 둔다. 값은 원문에서 계산하는 앱 코드라 `python -m app.collectors.sources register`
가 채운다(리비전이 그 시점 코드에 묶이지 않게 — 0020 의 canonical_url 과 같은 이유).

downgrade 는 세 칸을 지운다. 지금 들어가는 값은 모두 원문에서 다시 계산할 수 있다
(시각은 원문 시각, 종목은 리포트의 item_code, 출처 ID 는 url). 다른 방식의 종목 판단을
저장하기 시작하면 그 값은 다시 만들 수 없으므로 downgrade 를 막는 검사를 더한다.

Revision ID: 0024_source_card_stocks
Revises: 0023_analyst_report_purge
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_source_card_stocks"
down_revision: str | None = "0023_analyst_report_purge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_card", sa.Column("available_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_source_card_available_at", "source_card", ["available_at"])

    op.create_table(
        "source_card_stocks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_card_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("tagged_by", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_card_id"], ["source_card.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_card_id", "stock_code", name="uq_source_card_stock"),
    )
    op.create_index("ix_source_card_stocks_stock_code", "source_card_stocks", ["stock_code"])

    op.add_column(
        "stock_move_analysis_factor_sources",
        sa.Column("source_card_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_stock_move_analysis_source_card_id",
        "stock_move_analysis_factor_sources",
        "source_card",
        ["source_card_id"],
        ["id"],
    )
    op.create_index(
        "ix_stock_move_analysis_factor_sources_source_card_id",
        "stock_move_analysis_factor_sources",
        ["source_card_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_move_analysis_factor_sources_source_card_id",
        table_name="stock_move_analysis_factor_sources",
    )
    op.drop_constraint(
        "fk_stock_move_analysis_source_card_id",
        "stock_move_analysis_factor_sources",
        type_="foreignkey",
    )
    op.drop_column("stock_move_analysis_factor_sources", "source_card_id")
    op.drop_index("ix_source_card_stocks_stock_code", table_name="source_card_stocks")
    op.drop_table("source_card_stocks")
    op.drop_index("ix_source_card_available_at", table_name="source_card")
    op.drop_column("source_card", "available_at")
