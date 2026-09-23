"""표 설계가 실수로 바뀌는 걸 잡는다. DB 가 없어도 돈다 — 메타데이터만 본다.

이름과 적재 정책은 backend 가 읽게 될 계약이라, 바꾸면 테스트가 먼저 깨져야 한다.
"""

from app.core.database import Base
from app.models import (
    StockMoveAnalysis,
    StockMoveAnalysisFactor,
    StockMoveAnalysisFactorSource,
    StockMoveAnalysisReview,
)


def test_table_names_do_not_collide_with_backend_report() -> None:
    """backend 와 같은 Postgres 를 쓴다. 이름이 겹치면 backend 의 create_all 이 만든
    표를 여기 alembic 이 자기 것으로 알고 고치려 들거나, 그 반대가 된다. backend 의
    report / report_block / report_citation 과 겹치지 않아야 하고,
    analyst_reports(증권사 원문)와도 이름만 보고 구분돼야 한다."""
    assert StockMoveAnalysis.__tablename__ == "stock_move_analyses"
    assert StockMoveAnalysisFactor.__tablename__ == "stock_move_analysis_factors"
    assert StockMoveAnalysisFactorSource.__tablename__ == "stock_move_analysis_factor_sources"
    assert StockMoveAnalysisReview.__tablename__ == "stock_move_analysis_reviews"

    collisions = {"report", "report_block", "report_citation", "analyst_reports"}
    assert collisions.isdisjoint(
        {
            StockMoveAnalysis.__tablename__,
            StockMoveAnalysisFactor.__tablename__,
            StockMoveAnalysisFactorSource.__tablename__,
            StockMoveAnalysisReview.__tablename__,
        }
    )


def test_natural_key_has_no_unique_constraint() -> None:
    """(ticker, target_date, as_of) 는 자연키지만 유일하지 않다. 시스템 프롬프트가
    '이전 회차를 언급하지 않는다'고 규정해 각 회차가 독립 문서이고, 같은 기준시각의
    재생성도 새 행으로 쌓아야 한다. UNIQUE 가 붙으면 그 적재가 막힌다."""
    t = Base.metadata.tables["stock_move_analyses"]
    natural_key = {"ticker", "target_date", "as_of"}
    for uq in t.constraints:
        assert {c.name for c in uq.columns} != natural_key, "자연키에 UNIQUE 가 붙었다"
    assert "ix_stock_move_analysis_ticker_as_of" in {i.name for i in t.indexes}


def test_raw_json_is_not_nullable() -> None:
    """스키마 위반·파싱 실패 케이스가 반드시 나온다. 정규화 칼럼이 비더라도
    원본이 남아 있어야 원인을 되짚을 수 있다."""
    assert not Base.metadata.tables["stock_move_analyses"].columns["raw_json"].nullable


def test_normalized_columns_are_all_nullable() -> None:
    """검증 실패 건도 버리지 않고 상태만 달아 적재한다. ticker 조차 못 읽는 회차가
    있으므로 NOT NULL 을 걸면 그 행이 통째로 사라진다. counter 는 그와 별개로
    '방향이 어긋나는 재료가 없는 날'이라는 정상값으로도 NULL 이 된다."""
    cols = Base.metadata.tables["stock_move_analyses"].columns
    for name in (
        "ticker",
        "name",
        "target_date",
        "as_of",
        "change_pct",
        "verdict",
        "summary_move",
        "summary_counter",
    ):
        assert cols[name].nullable, f"{name} 에 NOT NULL 이 붙었다"


def test_verification_fields_are_stored_though_never_displayed() -> None:
    """quote / match / is_market_recap / not_found 는 서비스 화면에 나가지 않지만
    사후 환각 추적 수단이 이것뿐이다. 노출 제어는 backend 응답 단계에서 한다."""
    src = Base.metadata.tables["stock_move_analysis_factor_sources"].columns
    assert {"quote", "match", "is_market_recap"} <= set(src.keys())
    assert "not_found" in Base.metadata.tables["stock_move_analyses"].columns


def test_source_kind_column_exists_now() -> None:
    """지금은 전부 telegram 이지만 뉴스·리포트가 붙을 때 소스별 오탐률을 갈라 봐야
    한다. 그때 추가하면 이미 쌓인 데이터가 전부 미상이 된다.
    이름은 analyst_reports.source 관례를 따랐다."""
    col = Base.metadata.tables["stock_move_analysis_factor_sources"].columns["source"]
    assert not col.nullable
    assert col.default.arg == "telegram"


def test_not_verified_is_the_default_status() -> None:
    """failed 가 기본이면 '검증해서 떨어진 것'과 구분이 안 되고, passed 가 기본이면
    미검증 보고서가 backend 조회(verify_status='passed')로 샌다."""
    cols = Base.metadata.tables["stock_move_analyses"].columns
    assert cols["verify_status"].default.arg == "not_verified"
    assert cols["parse_status"].default.arg == "ok"


def test_review_decision_lives_in_a_separate_table() -> None:
    """AI 서버(적재)와 검수 쪽이 같은 행을 건드리면 단방향이 깨진다. 보고서는
    INSERT only 로 두고 판정은 별도 표에 쌓는다."""
    analysis_cols = set(Base.metadata.tables["stock_move_analyses"].columns.keys())
    assert "decision" not in analysis_cols
    assert "reviewer" not in analysis_cols
    assert "decision" in Base.metadata.tables["stock_move_analysis_reviews"].columns


def test_wrapper_duplicate_metrics_are_not_stored() -> None:
    """래퍼의 verdict / n_factors / n_sources 는 final_text 안의 값을 다시 센 것이고
    duration_ms / cost_usd 는 운영 지표다. 두 군데 있으면 어긋났을 때 무엇을 믿을지
    문제가 된다. 단일 출처는 final_text 다."""
    cols = set(Base.metadata.tables["stock_move_analyses"].columns.keys())
    assert cols.isdisjoint({"n_factors", "n_sources", "duration_ms", "cost_usd"})


def test_all_datetime_columns_are_timezone_aware() -> None:
    """루트 CLAUDE.md 가 naive datetime 을 금지한다. as_of 는 프롬프트가 'HH:MM'
    문자열로 주는 값이라 특히 새기 쉽다."""
    cols = Base.metadata.tables["stock_move_analyses"].columns
    for name in ("as_of", "generated_at", "loaded_at"):
        assert cols[name].type.timezone, f"{name} 가 naive 다"
    src = Base.metadata.tables["stock_move_analysis_factor_sources"].columns
    assert src["datetime_kst"].type.timezone
