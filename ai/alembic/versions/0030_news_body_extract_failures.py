"""count body extract failures per news row

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

news.body_extract_failures 를 더한다. 본문을 열었다가 추출 실패·알 수 없는 실패로 못 얻은 횟수다.
그런 실패를 정해진 횟수만큼 한 기사는 더 열지 않는다(services/news/failure.py).
일시 실패·429·영구 실패는 횟수로 포기하지 않으므로 세지 않는다.

    기존 실패 행  본문을 연 시각(body_fetched_at)이 있고 사유가 추출 실패·알 수 없는 실패면
                  한 번 실패한 것으로 1 을 넣는다. 이관 전 행(unrecorded)도 collected_at 으로
                  채워져 있어 1 이 된다. 몇 번 실패했는지는 남아 있지 않으므로 그보다 크게
                  잡지 않는다
    그 밖의 행    0

사유 판별은 failure.py 의 failure_kind 를 이 시점 그대로 SQL 로 옮겼다. 리비전은 앱 코드를
쓰지 않는다(규칙이 바뀌어도 이 리비전의 결과는 바뀌지 않아야 한다). dart_status 는 news 에
저장되지 않으므로 옮기지 않았다.

downgrade 는 칼럼만 지운다. 횟수가 사라지면 추출 실패 기사를 처음부터 다시 세어 몇 번 더 열 뿐,
본문·인용에는 영향이 없다.

번호는 다른 브랜치가 쓰는 0028·0029 와 겹치지 않게 0030 으로 했다. 0028(#96)·0029(#99) 가
먼저 develop 에 들어가므로 그 마지막 리비전(0029)을 잇는다(머리가 둘이면
`alembic upgrade head` 가 멈춘다).

Revision ID: 0030_news_body_extract_failures
Revises: 0029_classification_same_event
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_news_body_extract_failures"
down_revision: str | None = "0029_classification_same_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# body_error 가 영구·일시·429 실패인가(failure_kind 가 permanent·transient·rate_limited).
# 아니면 extract·unknown 이다. 사유가 비었거나(NULL·'') 처음 보는 사유도 unknown 이다.
#   http_error: <숫자>, 예전 http_<3자리>   HTTP 오류는 코드와 관계없이 셋 중 하나다
#   not_html·pdf·too_large·blocked·blocked_address   영구
#   request_failed(invalid_address 면 영구)·error   일시 또는 영구
_NOT_COUNTED = """
    btrim(split_part(body_error, ':', 1)) IN (
        'not_html', 'pdf', 'too_large', 'blocked', 'blocked_address', 'request_failed', 'error'
    )
    OR btrim(split_part(body_error, ':', 1)) ~ '^http_[0-9]{3}$'
    OR (btrim(split_part(body_error, ':', 1)) = 'http_error'
        AND btrim(substr(body_error, strpos(body_error, ':') + 1)) ~ '^[0-9]+$')
"""


def upgrade() -> None:
    op.add_column(
        "news", sa.Column("body_extract_failures", sa.Integer(), server_default="0", nullable=False)
    )
    op.execute(
        "UPDATE news SET body_extract_failures = 1"
        " WHERE body_status = 'failed' AND body_fetched_at IS NOT NULL"
        f" AND NOT coalesce({_NOT_COUNTED}, false)"
    )


def downgrade() -> None:
    op.drop_column("news", "body_extract_failures")
