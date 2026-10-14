"""add telegram message tables

텔레그램 메시지 원문(telegram_messages)과 메시지에서 발견한 링크·첨부
(telegram_message_links)를 만든다. 설계 근거는 `app/models/telegram_message.py` 에 있다.
전달된 글의 원 출처(forwarded_from)와 보관 정책상 삭제 기록(purged_at·purge_reason)도 함께 둔다.

channel 은 backend 가 관리하는 표다. FK 로만 가리키고 구조는 건드리지 않는다.
backend 리비전을 먼저 적용해야 한다(channel 이 없으면 중단).

Revision ID: 0021_telegram_messages
Revises: 0020_news_ai_managed
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_telegram_messages"
down_revision: str | None = "0020_news_ai_managed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF to_regclass('channel') IS NULL THEN
                RAISE EXCEPTION 'channel table is missing. Apply backend migrations first (cd backend && uv run alembic upgrade head), then run this upgrade again.'
                    USING HINT = 'See ai/README.md for the install order of an empty database.';
            END IF;
        END $$
    """)
    op.create_table(
        "telegram_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("msg_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("attachment_name", sa.Text(), nullable=True),
        sa.Column("forwarded_from", sa.Text(), nullable=True),
        sa.Column("forwarded_from_url", sa.Text(), nullable=True),
        sa.Column(
            "hidden_links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("views", sa.String(length=32), nullable=True),
        sa.Column("edited", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("edit_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_reason", sa.Text(), nullable=True),
        sa.Column("collected_via", sa.String(length=16), nullable=False),
        sa.Column(
            "collected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "collected_via IN ('web', 'telethon')", name="ck_telegram_message_collected_via"
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channel.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id", "msg_id", name="uq_telegram_message_channel_msg"),
    )
    op.create_index("ix_telegram_messages_posted_at", "telegram_messages", ["posted_at"])

    op.create_table(
        "telegram_message_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("discovered_url", sa.Text(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("news_id", sa.Integer(), nullable=True),
        sa.Column("analyst_report_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('url', 'attachment')", name="ck_telegram_message_link_kind"),
        sa.CheckConstraint(
            "(kind = 'url') = (discovered_url IS NOT NULL)", name="ck_telegram_message_link_url"
        ),
        sa.CheckConstraint(
            "num_nonnulls(news_id, analyst_report_id) <= 1", name="ck_telegram_message_link_target"
        ),
        sa.ForeignKeyConstraint(["analyst_report_id"], ["analyst_reports.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["telegram_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["news_id"], ["news.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id", "kind", "position", name="uq_telegram_message_link_position"
        ),
    )
    op.create_index(
        "ix_telegram_message_links_analyst_report_id",
        "telegram_message_links",
        ["analyst_report_id"],
    )
    op.create_index("ix_telegram_message_links_news_id", "telegram_message_links", ["news_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_message_links_news_id", table_name="telegram_message_links")
    op.drop_index(
        "ix_telegram_message_links_analyst_report_id", table_name="telegram_message_links"
    )
    op.drop_table("telegram_message_links")
    op.drop_index("ix_telegram_messages_posted_at", table_name="telegram_messages")
    op.drop_table("telegram_messages")
