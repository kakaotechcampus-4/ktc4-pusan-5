"""add dart disclosures

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

DART 공시 목록을 저장하는 표를 만든다. 설계 근거는 `app/models/dart_disclosure.py` 에 있다.

    dart_disclosures   한 행 = 공시 한 건. 접수번호(rcept_no)가 키다

새 표라 넘겨받는 데이터가 없다. downgrade 는 표를 지운다 — 목록은 DART 에서 다시 받을 수
있다. 다만 first_seen_at(처음 본 시각)은 다시 만들 수 없으므로 행이 있으면 지우지 않고 멈춘다.

Revision ID: 0025_dart_disclosures
Revises: 0024_source_card_stocks
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_dart_disclosures"
down_revision: str | None = "0024_source_card_stocks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dart_disclosures",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rcept_no", sa.String(length=14), nullable=False),
        sa.Column("corp_code", sa.String(length=8), nullable=False),
        sa.Column("corp_name", sa.String(length=200), nullable=False),
        sa.Column("stock_code", sa.String(length=6), nullable=False),
        sa.Column("report_nm", sa.Text(), nullable=False),
        sa.Column("flr_nm", sa.String(length=200), nullable=False),
        sa.Column("rcept_dt", sa.Date(), nullable=False),
        sa.Column("rm", sa.String(length=20), nullable=True),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rcept_no", name="uq_dart_disclosure_rcept_no"),
    )
    op.create_index(
        "ix_dart_disclosures_stock_date", "dart_disclosures", ["stock_code", "rcept_dt"]
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM dart_disclosures) THEN
                RAISE EXCEPTION 'dart_disclosures 에 행이 있다. first_seen_at 은 다시 만들 수 '
                                '없으므로 지우지 않는다. 필요 없으면 직접 비운 뒤 내린다.';
            END IF;
        END $$;
        """
    )
    op.drop_index("ix_dart_disclosures_stock_date", table_name="dart_disclosures")
    op.drop_table("dart_disclosures")
