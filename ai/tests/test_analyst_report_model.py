"""표 설계가 실수로 바뀌는 걸 잡는다. DB 가 없어도 돈다 — 메타데이터만 본다.

이름과 자연키는 다른 팀원이 참조하게 될 계약이라, 바꾸면 테스트가 먼저 깨져야 한다.
"""

from app.core.database import Base
from app.models import AnalystReport


def test_표_이름은_analyst_reports_다() -> None:
    """report / report_block / report_citation 은 우리 서비스가 생성하는 산출물이고
    이건 증권사 애널리스트가 쓴 원문이다. 같은 DB 에서 이름이 겹치면 구분이 안 된다."""
    assert AnalystReport.__tablename__ == "analyst_reports"
    assert "analyst_reports" in Base.metadata.tables


def test_자연키는_출처_카테고리_원본ID_다() -> None:
    """네이버 researchId 는 카테고리마다 별도 시퀀스다(company 96141, industry 46078).
    researchId 만으로는 충돌하므로 셋을 묶어야 재수집이 멱등해진다."""
    t = Base.metadata.tables["analyst_reports"]
    uq = [c for c in t.constraints if c.name == "uq_analyst_report_source_id"]
    assert uq, "uq_analyst_report_source_id 가 없다"
    assert {c.name for c in uq[0].columns} == {"source", "category", "source_id"}


def test_담지_않기로_한_칼럼은_없다() -> None:
    """analyst(애널리스트명): 네이버가 안 주고 PDF 추정은 채움률 41%에 오탐.
    prev_goal_price: 네이버의 prevGoalPrice 는 직전 목표주가가 아니라 현재가 중복이다."""
    cols = set(Base.metadata.tables["analyst_reports"].columns.keys())
    assert "analyst" not in cols
    assert "prev_goal_price" not in cols


def test_발행기관은_비어도_된다() -> None:
    """텔레그램 재배포물엔 증권사가 아닌 발행처(기업 IR 자료)나 본문 없는 스캔 PDF 가
    섞여 들어온다. 못 찾을 때 채널명을 넣으면 거짓 출처가 되므로 NULL 을 허용한다."""
    assert Base.metadata.tables["analyst_reports"].columns["broker"].nullable


def test_검색에_쓰는_인덱스가_있다() -> None:
    names = {i.name for i in Base.metadata.tables["analyst_reports"].indexes}
    assert "ix_analyst_report_code_date" in names   # 종목 + 날짜
    assert "ix_analyst_report_date" in names        # 날짜
    assert "ix_analyst_report_broker_date" in names  # 발행기관 + 날짜
