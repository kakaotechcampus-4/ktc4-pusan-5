"""record retention purges on analyst_reports

보관 정책으로 PDF 본문을 지울 수 있게 analyst_reports 에 삭제 시각·사유 칸을 더한다.
지운 행은 body_status = 'purged' 이고 body_text 가 비어 있다. 행·식별키·PDF 해시는 남긴다.
news·telegram_messages 는 0020·0021 에서 같은 칸을 함께 만들었다. 기존 행은 건드리지 않는다.

downgrade 는 본문을 지운 행이 있으면 중단한다. 칸을 지우면 지운 기록을 잃고, 예전 코드는
purged 를 모르므로 다음 네이버 수집이 본문을 다시 채운다.

Revision ID: 0023_analyst_report_purge
Revises: 0022_source_card_sources
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023_analyst_report_purge"
down_revision: str | None = "0022_source_card_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyst_reports", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("analyst_reports", sa.Column("purge_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("""
        DO $$
        DECLARE
            purged bigint;
        BEGIN
            SELECT count(*) INTO purged FROM analyst_reports
            WHERE body_status = 'purged' OR purged_at IS NOT NULL;
            IF purged > 0 THEN
                RAISE EXCEPTION 'Cannot drop analyst_reports purge records: % row(s) had their body removed by the retention policy. Keep this revision; no rows were changed.', purged;
            END IF;
        END $$
    """)
    op.drop_column("analyst_reports", "purge_reason")
    op.drop_column("analyst_reports", "purged_at")
