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

기존 행은 raw_json 으로 채운다. 규칙은 적재(`repositories/stock_move_analysis.py` 의 build_analysis)를
따른다 — 타입이 어긋난 값은 NULL, 시간대 없는 시각은 KST, 객체가 아닌 link(중첩 배열 포함)는 뺀다.
파싱이 깨진 행(parse_failed)은 raw_json 이 래퍼라 채우지 않는다. 적재도 그 행의 보고서 칸을 비운다.
새 칸이 하나도 없는 옛 형식 행은 고치지 않는다(다시 쓰면 행 수만큼 표가 불어난다).

display_as_of 는 러너가 쓰는 꼴만 받는다: 확장 ISO 8601 날짜·시각(분까지 필수, 초·소수 6자리까지
선택), 오프셋은 Z·±HH·±HHMM·±HH:MM 이고 없으면 KST. 그 밖은 NULL 이다. 적재(datetime.fromisoformat)는
더 넓게 받아서 날짜만·시만·기본 형식(20261103T1530)·쉼표 소수·소수 7자리 이상·초 단위 오프셋은
적재하면 값이 들고 이 리비전은 NULL 로 둔다. 러너는 isoformat() 으로만 적어 그런 값이 없다. 범위 밖 값
(24시, 초 60, 2월 30일)과 시간대 이름(UTC 등)은 둘 다 NULL 이다. 24시는 Postgres 가 다음 날 0시로 받지만
적재(파이썬 3.12 fromisoformat)는 받지 않아 정규식에서 시를 00~23 으로 막는다. 값 검사에 pg_input_is_valid 를
쓴다(PostgreSQL 16 이상).

relative_verdict 칼럼은 24자다. 그보다 긴 문자열이 있으면 표본 id 와 함께 멈춘다 — 이 리비전 전에는
칼럼이 없어 어떤 길이든 적재됐다. 러너는 이 값을 계산값으로 덮어써서(finalize.recompute_verdicts)
러너 산출물에는 없다.

skipped_llm 은 채우지 못한다. 보고서가 아니라 래퍼의 칸이라 파싱에 성공한 행의 raw_json(보고서)에 없다.
파싱 실패 행의 raw_json(래퍼)에는 있을 수 있지만 위 규칙대로 채우지 않는다 — 정형 보고서는 러너가
json.dumps 로 적어 파싱이 깨지지 않는다. 이 리비전 전에 적재된 정형 보고서는 skipped_llm 이 NULL 로 남는다.

표 잠금: 칼럼 추가가 두 표에 ACCESS EXCLUSIVE 를 잡고 커밋까지 놓지 않는다(한 트랜잭션). 잡기 전에
다른 트랜잭션이 표를 쥐고 있으면 그 뒤로 모든 조회가 줄을 서므로, 잠금 대기는 5초로 끊고 실패한다.
다시 돌리면 된다.

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


# 칼럼 추가·삭제의 잠금 대기 상한. 잠금을 잡은 뒤의 채우기에는 걸리지 않게 칼럼을 바꾼 직후 되돌린다.
LOCK_TIMEOUT = "5s"


def upgrade() -> None:
    op.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    # 채우기 전에 relative_verdict(24자)에 안 들어가는 값을 찾는다. 넘치면 UPDATE 가 행 하나 때문에 멈춰서
    # 어느 행인지 알 수 없다.
    op.execute("""
        DO $$
        DECLARE
            failed_count bigint;
            sample_ids bigint[];
        BEGIN
            SELECT count(*), (array_agg(id ORDER BY id))[1:5] INTO failed_count, sample_ids
            FROM stock_move_analyses
            WHERE parse_status <> 'parse_failed'
              AND jsonb_typeof(raw_json -> 'relative_verdict') = 'string'
              AND length(raw_json ->> 'relative_verdict') > 24;

            IF failed_count > 0 THEN
                RAISE EXCEPTION
                    'Cannot fill relative_verdict: % row(s) longer than 24 characters. Sample analysis IDs: %',
                    failed_count, sample_ids
                    USING HINT = 'Shorten or null raw_json.relative_verdict on those rows, then retry.';
            END IF;
        END $$
    """)

    op.add_column("stock_move_analyses", sa.Column("display_as_of", sa.DateTime(timezone=True), nullable=True))
    op.add_column("stock_move_analyses", sa.Column("display_is_close", sa.Boolean(), nullable=True))
    op.add_column("stock_move_analyses", sa.Column("relative_verdict", sa.String(length=24), nullable=True))
    op.add_column("stock_move_analyses", sa.Column("summary_relative", sa.Text(), nullable=True))
    op.add_column("stock_move_analyses", sa.Column("skipped_llm", sa.String(length=32), nullable=True))
    op.add_column(
        "stock_move_analysis_factors",
        sa.Column("links", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute("SET LOCAL lock_timeout = DEFAULT")

    # 문자열·불린이 아니면 NULL 이다(_as_str·_as_bool). summary 가 객체가 아니면 -> 가 NULL 을 준다.
    # display_as_of 는 docstring 의 꼴 전체가 맞아야 받는다. 오프셋이 있으면 그대로, 없으면 KST 로 본다
    # (_parse_kst_datetime). 앞뒤 공백은 str.strip() 처럼 탭·줄바꿈까지 벗긴다.
    # 칸 이름이 하나도 없는 행은 v 에서 빠져 고치지 않는다. JSON null 인 칸은 남지만 아래 CASE 가 NULL 을 준다.
    op.execute(r"""
        WITH v AS (
            SELECT id, btrim(raw_json ->> 'display_as_of', E' \t\n\r\f\x0B') AS shown
            FROM stock_move_analyses
            WHERE parse_status <> 'parse_failed'
              AND (raw_json -> 'relative_verdict' IS NOT NULL
                   OR raw_json -> 'display_as_of' IS NOT NULL
                   OR raw_json -> 'display_is_close' IS NOT NULL
                   OR raw_json -> 'summary' -> 'relative' IS NOT NULL)
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
                     OR v.shown !~ '^\d{4}-\d{2}-\d{2}[T ]([01]\d|2[0-3]):[0-5]\d(:[0-5]\d(\.\d{1,6})?)?(Z|[+-]\d{2}(:?\d{2})?)?$'
                     OR NOT pg_input_is_valid(v.shown, 'timestamptz') THEN NULL
                WHEN v.shown ~ '(Z|[+-]\d{2}(:?\d{2})?)$' THEN v.shown::timestamptz
                ELSE v.shown::timestamp AT TIME ZONE 'Asia/Seoul'
            END
        FROM v
        WHERE a.id = v.id
    """)
    # order_index 는 보고서 factors 배열의 자리다(객체가 아닌 factor 를 건너뛰어도 자리는 그대로).
    # strict 여야 한다. lax 는 필터 앞에서 원소 배열을 한 번 더 풀어 [[{...}]] 안의 객체를 살린다 — 적재는 버린다.
    # strict 의 $[*] 는 배열이 아니면 오류지만 WHERE 가 배열만 남긴다.
    op.execute("""
        UPDATE stock_move_analysis_factors f SET
            links = jsonb_path_query_array(a.raw_json -> 'factors' -> f.order_index -> 'links',
                                           'strict $[*] ? (@.type() == "object")')
        FROM stock_move_analyses a
        WHERE a.id = f.analysis_id
          AND a.parse_status <> 'parse_failed'
          AND jsonb_typeof(a.raw_json -> 'factors' -> f.order_index -> 'links') = 'array'
    """)


def downgrade() -> None:
    op.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
    op.drop_column("stock_move_analysis_factors", "links")
    op.drop_column("stock_move_analyses", "skipped_llm")
    op.drop_column("stock_move_analyses", "summary_relative")
    op.drop_column("stock_move_analyses", "relative_verdict")
    op.drop_column("stock_move_analyses", "display_is_close")
    op.drop_column("stock_move_analyses", "display_as_of")
    op.execute("SET LOCAL lock_timeout = DEFAULT")
