"""count failed body fetches per news row

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

news.body_failures 를 더한다. 본문을 열었다가 못 얻은 횟수다. 추출 실패를 정해진 횟수만큼 한
기사는 더 열지 않는다(services/news/failure.py).

    기존 실패 행  본문을 연 시각(body_fetched_at)이 있으면 한 번 실패한 것으로 1 을 넣는다.
                  이관 전 행도 collected_at 으로 채워져 있어 1 이 된다. 몇 번 실패했는지는
                  남아 있지 않으므로 그보다 크게 잡지 않는다
    그 밖의 행    0

downgrade 는 칼럼만 지운다. 횟수가 사라지면 추출 실패 기사를 처음부터 다시 세어 몇 번 더 열 뿐,
본문·인용에는 영향이 없다.

번호는 다른 브랜치가 쓰는 0028·0029 와 겹치지 않게 0030 으로 했다. 지금 develop 의 마지막
리비전(0027)을 잇는다. 0028·0029 가 먼저 develop 에 들어가면 Revises 를 그 마지막 리비전으로
바꿔야 한다(머리가 둘이면 `alembic upgrade head` 가 멈춘다).

Revision ID: 0030_news_body_failures
Revises: 0027_classification
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_news_body_failures"
down_revision: str | None = "0027_classification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "news", sa.Column("body_failures", sa.Integer(), server_default="0", nullable=False)
    )
    op.execute(
        "UPDATE news SET body_failures = 1"
        " WHERE body_status = 'failed' AND body_fetched_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("news", "body_failures")
