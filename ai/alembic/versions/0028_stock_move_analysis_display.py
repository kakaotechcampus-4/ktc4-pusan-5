"""add stock_move_analysis display columns

(첫 줄은 `alembic history` 가 제목으로 찍는다. 한국어 Windows 콘솔에서 깨지므로
영어로 쓰고, 설명은 아래에 한국어로 적는다.)

지금 보고서 형식에서 화면이 쓰는 칸을 칼럼으로 둔다. 지금까지는 조회가 raw_json 에서 꺼냈다.
칼럼 뜻은 `app/models/stock_move_analysis.py` 에 있다.

    stock_move_analyses.summary_relative     보고서 summary.relative
    stock_move_analyses.relative_verdict     보고서 relative_verdict
    stock_move_analyses.display_as_of        보고서 display_as_of (화면 기준 시각)
    stock_move_analyses.display_is_close     보고서 display_is_close
    stock_move_analyses.skipped_llm          래퍼 skipped_llm (정형 보고서 사유)
    stock_move_analysis_factors.links        보고서 factors[i].links

기존 행은 raw_json 으로 채운다. 규칙은 적재(`repositories/stock_move_analysis.py` 의 build_analysis)와
같다 — 타입이 어긋난 값은 NULL, 시간대 없는 시각은 KST, 객체가 아닌 link 는 뺀다. 파싱이 깨진 행
(parse_failed)은 raw_json 이 래퍼라 채우지 않는다. 적재도 그 행의 보고서 칸을 비운다.

skipped_llm 은 채우지 못한다. 보고서가 아니라 래퍼의 칸이라 raw_json 에 없다. 이 리비전 전에 적재된
정형 보고서는 skipped_llm 이 NULL 로 남는다.

display_as_of 를 안전하게 바꾸려고 pg_input_is_valid 를 쓴다(PostgreSQL 16 이상).

downgrade 는 여섯 칼럼을 지운다. skipped_llm 을 뺀 다섯은 raw_json 에서 다시 채워지지만 skipped_llm 은
다시 upgrade 해도 되살아나지 않는다. 정형 보고서는 LLM 없이 inputs_used 사본으로 다시 만들 수 있어
downgrade 를 막지 않는다.

Revision ID: 0028_stock_move_analysis_display
Revises: 0027_classification
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028_stock_move_analysis_display"
down_revision: str | None = "0027_classification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stock_move_analyses", sa.Column("display_as_of", sa.DateTime(timezone=True), nullable=True))
    op.add_column("stock_move_analyses", sa.Column("display_is_close", sa.Boolean(), nullable=True))
    op.add_column("stock_move_analyses", sa.Column("relative_verdict", sa.String(length=24), nullable=True))
    op.add_column("stock_move_analyses", sa.Column("summary_relative", sa.Text(), nullable=True))
    op.add_column("stock_move_analyses", sa.Column("skipped_llm", sa.String(length=32), nullable=True))
    op.add_column(
        "stock_move_analysis_factors",
        sa.Column("links", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # 문자열·불린이 아니면 NULL 이다(_as_str·_as_bool). summary 가 객체가 아니면 -> 가 NULL 을 준다.
    # display_as_of 는 날짜가 붙은 시각만 받는다. 오프셋이 있으면 그대로, 없으면 KST 로 본다(_parse_kst_datetime).
    op.execute(r"""
        WITH v AS (
            SELECT id, btrim(raw_json ->> 'display_as_of') AS shown
            FROM stock_move_analyses
            WHERE parse_status <> 'parse_failed'
        )
        UPDATE stock_move_analyses a SET
            relative_verdict = CASE WHEN jsonb_typeof(a.raw_json -> 'relative_verdict') = 'string'
                                    THEN a.raw_json ->> 'relative_verdict' END,
            summary_relative = CASE WHEN jsonb_typeof(a.raw_json -> 'summary' -> 'relative') = 'string'
                                    THEN a.raw_json -> 'summary' ->> 'relative' END,
            display_is_close = CASE WHEN jsonb_typeof(a.raw_json -> 'display_is_close') = 'boolean'
                                    THEN (a.raw_json ->> 'display_is_close')::boolean END,
            display_as_of = CASE
                WHEN jsonb_typeof(a.raw_json -> 'display_as_of') <> 'string'
                     OR v.shown !~ '^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}'
                     OR NOT pg_input_is_valid(v.shown, 'timestamptz') THEN NULL
                WHEN v.shown ~ '(Z|[+-]\d{2}(:?\d{2})?)$' THEN v.shown::timestamptz
                ELSE v.shown::timestamp AT TIME ZONE 'Asia/Seoul'
            END
        FROM v
        WHERE a.id = v.id
    """)
    # order_index 는 보고서 factors 배열의 자리다(객체가 아닌 factor 를 건너뛰어도 자리는 그대로).
    op.execute("""
        UPDATE stock_move_analysis_factors f SET
            links = jsonb_path_query_array(a.raw_json -> 'factors' -> f.order_index -> 'links',
                                           '$[*] ? (@.type() == "object")')
        FROM stock_move_analyses a
        WHERE a.id = f.analysis_id
          AND a.parse_status <> 'parse_failed'
          AND jsonb_typeof(a.raw_json -> 'factors' -> f.order_index -> 'links') = 'array'
    """)


def downgrade() -> None:
    op.drop_column("stock_move_analysis_factors", "links")
    op.drop_column("stock_move_analyses", "skipped_llm")
    op.drop_column("stock_move_analyses", "summary_relative")
    op.drop_column("stock_move_analyses", "relative_verdict")
    op.drop_column("stock_move_analyses", "display_is_close")
    op.drop_column("stock_move_analyses", "display_as_of")
