"""take over the news table from backend

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

backend 첫 리비전(99dbfe02fd98)이 만든 news 를 AI 가 넘겨받는다. 표를 새로 만들지 않고
기존 행·id 를 그대로 둔 채 칼럼만 더한다. 이 리비전부터 news 의 구조는 ai/alembic 이 관리하고,
backend migrations/env.py 는 news 를 비교에서 뺀다.

    published_at     NOT NULL → NULL 허용. 텔레그램 링크로 연 기사는 발행 시각을 모른다
    canonical_url    중복 판정용 정규화 주소. 기존 행은 비워 두고 등록 처리
                     (collectors/sources.py)가 채운다. 정규화 규칙이 앱 코드라 여기서 계산하면
                     리비전이 그 시점 코드에 묶인다
    body_status      ok | failed | purged. 기존 행은 본문이 있으면 ok, 없으면 failed.
                     purged 는 보관 정책으로 본문을 지운 행이다(purged_at·purge_reason)
    body_error       기존 실패 행은 backend 가 사유를 남기지 않아 'unrecorded'
    body_fetched_at  기존 행은 collected_at. backend 는 본문을 받은 직후 같은 실행에서
                     행을 넣었으므로 본문을 받은 시각의 상한이다
    body_extractor   기존 본문은 backend 의 trafilatura 로 뽑은 것이다

**backend 리비전을 먼저 적용해야 한다.** news 가 없으면 중단한다. 여기서 news 를 만들면
나중에 backend 첫 리비전이 같은 표를 다시 만들려다 실패한다.

downgrade 는 발행 시각이 없는 행이나 보관 정책으로 본문을 지운 행이 있으면 중단한다. 행을
지우거나 값을 지어내지 않고, 지운 기록을 잃어 본문이 되살아나는 일도 막는다.

Revision ID: 0020_news_ai_managed
Revises: 0019_stock_move_analysis
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_news_ai_managed"
down_revision: str | None = "0019_stock_move_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF to_regclass('news') IS NULL THEN
                RAISE EXCEPTION 'news table is missing. Apply backend migrations first (cd backend && uv run alembic upgrade head), then run this upgrade again.'
                    USING HINT = 'See ai/README.md for the install order of an empty database.';
            END IF;
        END $$
    """)
    op.alter_column(
        "news", "published_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )
    op.add_column("news", sa.Column("canonical_url", sa.Text(), nullable=True))
    op.add_column("news", sa.Column("body_status", sa.String(length=16), nullable=True))
    op.add_column("news", sa.Column("body_error", sa.Text(), nullable=True))
    op.add_column("news", sa.Column("body_fetched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("news", sa.Column("body_extractor", sa.String(length=32), nullable=True))
    op.add_column("news", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("news", sa.Column("purge_reason", sa.Text(), nullable=True))
    # cleaned_text 가 NULL 이면 비교 결과도 NULL 이라 ELSE 로 간다. 빈 문자열도 본문이 아니다.
    op.execute("""
        UPDATE news SET
            body_status = CASE WHEN cleaned_text <> '' THEN 'ok' ELSE 'failed' END,
            body_error = CASE WHEN cleaned_text <> '' THEN NULL ELSE 'unrecorded' END,
            body_extractor = CASE WHEN cleaned_text <> '' THEN 'trafilatura' END,
            body_fetched_at = collected_at
    """)
    op.alter_column(
        "news", "body_status", existing_type=sa.String(length=16), nullable=False
    )
    op.create_unique_constraint("uq_news_canonical_url", "news", ["canonical_url"])
    op.create_check_constraint(
        "ck_news_body_status", "news", "body_status IN ('ok', 'failed', 'purged')"
    )


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            undated bigint;
            purged bigint;
        BEGIN
            SELECT count(*) INTO undated FROM news WHERE published_at IS NULL;
            IF undated > 0 THEN
                RAISE EXCEPTION 'Cannot restore NOT NULL on news.published_at: % row(s) have no publish time. Keep this revision; no rows were deleted.', undated;
            END IF;
            SELECT count(*) INTO purged FROM news WHERE body_status = 'purged';
            IF purged > 0 THEN
                RAISE EXCEPTION 'Cannot drop news purge records: % row(s) had their body removed by the retention policy. Keep this revision; no rows were changed.', purged;
            END IF;
        END $$
    """)
    op.drop_constraint("ck_news_body_status", "news", type_="check")
    op.drop_constraint("uq_news_canonical_url", "news", type_="unique")
    op.drop_column("news", "purge_reason")
    op.drop_column("news", "purged_at")
    op.drop_column("news", "body_extractor")
    op.drop_column("news", "body_fetched_at")
    op.drop_column("news", "body_error")
    op.drop_column("news", "body_status")
    op.drop_column("news", "canonical_url")
    op.alter_column(
        "news", "published_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
