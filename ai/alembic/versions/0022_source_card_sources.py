"""link source_card to raw source rows

backend 첫 리비전(99dbfe02fd98)이 만든 source_card 를 AI 가 넘겨받아 공통 자료 목록으로 쓴다.
기존 칼럼은 그대로 두고, 종류별 원문 표를 가리키는 FK 세 개와 제약을 더한다.
설계 근거는 `app/models/source_card.py` 에 있다. backend 는 이 표를 비교에서 뺀다.

    news_id               → news.id               card_type = 'news'
    analyst_report_id     → analyst_reports.id    card_type = 'pdf'
    telegram_message_id   → telegram_messages.id  card_type = 'message'

이미 news·pdf·message 종류의 카드가 원문 FK 없이 들어 있으면 새 제약을 어기므로 중단한다.
기존 카드를 고치거나 지우지 않는다. 그런 카드는 backend 와 정리한 뒤 다시 실행한다.

downgrade 는 원문을 가리키는 카드가 하나라도 있으면 중단한다. FK 를 지우면 그 카드가
무엇을 가리켰는지 잃는다. report_citation 이 그 카드를 인용하고 있을 수도 있다.

Revision ID: 0022_source_card_sources
Revises: 0021_telegram_messages
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_source_card_sources"
down_revision: str | None = "0021_telegram_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RAW_SOURCE_CHECK = (
    "(card_type = 'news') = (news_id IS NOT NULL)"
    " AND (card_type = 'pdf') = (analyst_report_id IS NOT NULL)"
    " AND (card_type = 'message') = (telegram_message_id IS NOT NULL)"
)


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            conflicting bigint;
        BEGIN
            IF to_regclass('source_card') IS NULL THEN
                RAISE EXCEPTION 'source_card table is missing. Apply backend migrations first (cd backend && uv run alembic upgrade head), then run this upgrade again.'
                    USING HINT = 'See ai/README.md for the install order of an empty database.';
            END IF;
            SELECT count(*) INTO conflicting FROM source_card
            WHERE card_type IN ('news', 'pdf', 'message');
            IF conflicting > 0 THEN
                RAISE EXCEPTION 'Cannot link source_card to raw sources: % existing card(s) already use card_type news/pdf/message without a raw source row. No rows were changed.', conflicting;
            END IF;
        END $$
    """)
    op.add_column("source_card", sa.Column("news_id", sa.Integer(), nullable=True))
    op.add_column("source_card", sa.Column("analyst_report_id", sa.BigInteger(), nullable=True))
    op.add_column("source_card", sa.Column("telegram_message_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key("fk_source_card_news_id", "source_card", "news", ["news_id"], ["id"])
    op.create_foreign_key(
        "fk_source_card_analyst_report_id",
        "source_card",
        "analyst_reports",
        ["analyst_report_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_source_card_telegram_message_id",
        "source_card",
        "telegram_messages",
        ["telegram_message_id"],
        ["id"],
    )
    op.create_unique_constraint("uq_source_card_news_id", "source_card", ["news_id"])
    op.create_unique_constraint(
        "uq_source_card_analyst_report_id", "source_card", ["analyst_report_id"]
    )
    op.create_unique_constraint(
        "uq_source_card_telegram_message_id", "source_card", ["telegram_message_id"]
    )
    op.create_check_constraint("ck_source_card_raw_source", "source_card", RAW_SOURCE_CHECK)


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            linked bigint;
        BEGIN
            SELECT count(*) INTO linked FROM source_card
            WHERE num_nonnulls(news_id, analyst_report_id, telegram_message_id) > 0;
            IF linked > 0 THEN
                RAISE EXCEPTION 'Cannot unlink source_card: % card(s) point to raw source rows. Keep this revision; no rows were deleted.', linked;
            END IF;
        END $$
    """)
    op.drop_constraint("ck_source_card_raw_source", "source_card", type_="check")
    op.drop_constraint("uq_source_card_telegram_message_id", "source_card", type_="unique")
    op.drop_constraint("uq_source_card_analyst_report_id", "source_card", type_="unique")
    op.drop_constraint("uq_source_card_news_id", "source_card", type_="unique")
    op.drop_constraint("fk_source_card_telegram_message_id", "source_card", type_="foreignkey")
    op.drop_constraint("fk_source_card_analyst_report_id", "source_card", type_="foreignkey")
    op.drop_constraint("fk_source_card_news_id", "source_card", type_="foreignkey")
    op.drop_column("source_card", "telegram_message_id")
    op.drop_column("source_card", "analyst_report_id")
    op.drop_column("source_card", "news_id")
