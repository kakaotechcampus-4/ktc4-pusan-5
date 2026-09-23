"""표 설계가 실수로 바뀌는 걸 잡는다. DB 가 없어도 돈다 — 메타데이터만 본다.

이름과 자연키는 다른 팀원이 참조하게 될 계약이라, 바꾸면 테스트가 먼저 깨져야 한다.
"""

from app.core.database import Base
from app.models import AnalystReport


def test_table_name_is_analyst_reports() -> None:
    """report / report_block / report_citation 은 우리 서비스가 생성하는 산출물이고
    이건 증권사 애널리스트가 쓴 원문이다. 같은 DB 에서 이름이 겹치면 구분이 안 된다."""
    assert AnalystReport.__tablename__ == "analyst_reports"
    assert "analyst_reports" in Base.metadata.tables


def test_natural_key_is_source_category_and_source_id() -> None:
    """원본ID 는 출처가 자기 구분 안에서만 유일하게 매긴다.

    네이버 researchId 는 카테고리마다 별도 시퀀스이고(company 96141, industry 46078)
    텔레그램 메시지 번호는 채널 안에서만 유일하다. 그 구분까지 묶어야 재수집이 멱등해진다.
    """
    t = Base.metadata.tables["analyst_reports"]
    uq = [c for c in t.constraints if c.name == "uq_analyst_report_source_id"]
    assert uq, "uq_analyst_report_source_id 가 없다"
    assert {c.name for c in uq[0].columns} == {"source", "source_category", "source_id"}


def test_natural_key_does_not_use_our_category() -> None:
    """자연키에 category 를 쓰면 안 된다. 우리가 정하는 값이라 바뀌기 때문이다.

    실측(2026-09-18): invest 2026-01-16 자 researchId 37550 과
    daily 2026-09-17 자 37550 이 둘 다 살아 있고 같은 번호대에서 42건이 겹쳤다.
    둘을 market 으로 합쳐서 넣으면 한쪽이 다른 쪽을 덮어쓴다. 에러는 안 난다.
    """
    t = Base.metadata.tables["analyst_reports"]
    uq = next(c for c in t.constraints if c.name == "uq_analyst_report_source_id")
    assert "category" not in {c.name for c in uq.columns}


def test_intentionally_omitted_columns_are_absent() -> None:
    """analyst(애널리스트명): 네이버가 안 주고 PDF 추정은 채움률 41%에 오탐.
    prev_goal_price: 네이버의 prevGoalPrice 는 직전 목표주가가 아니라 현재가 중복이다."""
    cols = set(Base.metadata.tables["analyst_reports"].columns.keys())
    assert "analyst" not in cols
    assert "prev_goal_price" not in cols


def test_broker_is_nullable() -> None:
    """텔레그램 재배포물엔 증권사가 아닌 발행처(기업 IR 자료)나 본문 없는 스캔 PDF 가
    섞여 들어온다. 못 찾을 때 채널명을 넣으면 거짓 출처가 되므로 NULL 을 허용한다."""
    assert Base.metadata.tables["analyst_reports"].columns["broker"].nullable


def test_search_indexes_exist() -> None:
    """종목별·날짜별 조회에 쓰는 인덱스가 걸려 있는지."""
    names = {i.name for i in Base.metadata.tables["analyst_reports"].indexes}
    assert "ix_analyst_report_code_date" in names   # 종목 + 날짜
    assert "ix_analyst_report_date" in names        # 날짜
    assert "ix_analyst_report_broker_date" in names  # 발행기관 + 날짜
