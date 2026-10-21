"""종목별 조립 (DRAFT 5절). 표 없이 조회로 한다.

종목 X 에 붙는 사건을 세 갈래로 찾는다.

    company   사건의 대상에 X 가 있다 (scope 무관)       직접
    industry  scope = industry 이고 대상 산업이 X 의       간접 — 배경 후보
              산업 자신이거나 그 뉴스용 상위
    macro     scope = macro                              공통 배경 후보
    market    scope = market                             공통 배경 후보

- 한 사건이 여러 갈래에 걸리면 위쪽 하나로 낸다(company > industry > macro·market).
- 회사 사건에 산업 표기가 섞여도 industry 갈래를 타지 않는다. 다른 회사로 퍼지지 않게 한다.
- 산업 연결은 기준에서 **확인된** 것만 쓴다(basis.industries_of).
- 등락만 말하는 사건(`role = price_move`)은 근거 후보에서 뺀다. "왜" 가 아니라 "얼마나" 이고,
  등락 수치는 시세 데이터가 맡는다(전제 P5). 이유가 같은 문장에 있으면 LLM 이 `cause` 로 낸다.
  추출 결과에는 남겨 두어 LLM 이 무엇을 price_move 로 봤는지 확인할 수 있게 한다.
  나중에 추출 단계에서 아예 내지 않게 바꾸면 이 규칙은 지운다.

여기는 순수 함수다. 기준 시각 조건(available_at <= T)과 현재 회차 선택은 DB 조회가 맡는다.
DB 표가 생기면 같은 규칙을 SQL 로 옮기고, 이 함수는 그 결과와 맞춰 보는 기준으로 남긴다.
"""

from dataclasses import dataclass

from app.services.classification.basis import Basis
from app.services.classification.events import Event
from app.services.classification.link import EntityLink

PATHS = ("company", "industry", "macro", "market")
# 근거 후보가 아닌 역할. 추출 결과에는 남지만 조립에 넣지 않는다
NON_EVIDENCE_ROLES = frozenset({"price_move"})


@dataclass(frozen=True)
class ClassifiedEvent:
    """분류를 마친 사건 하나. 회차·자료 ID 는 DB 가 생기면 채운다."""

    source_card_id: int
    event: Event
    links: tuple[EntityLink, ...]


@dataclass(frozen=True)
class AssembledEvent:
    source_card_id: int
    event: Event
    path: str  # PATHS 중 하나. company 만 직접, 나머지는 배경 후보

    @property
    def is_direct(self) -> bool:
        return self.path == "company"


def path_for(item: ClassifiedEvent, stock_code: str, reachable: set[str]) -> str | None:
    """이 사건이 종목에 어느 갈래로 붙는가. 안 붙으면 None."""
    if item.event.role in NON_EVIDENCE_ROLES:
        return None
    if any(link.stock_code == stock_code for link in item.links):
        return "company"
    scope = item.event.scope
    if scope == "industry" and any(link.industry_code in reachable for link in item.links):
        return "industry"
    if scope in ("macro", "market"):
        return scope
    return None


def assemble(items: list[ClassifiedEvent], stock_code: str, basis: Basis) -> list[AssembledEvent]:
    reachable = basis.reachable_industries(stock_code)
    out = []
    for item in items:
        path = path_for(item, stock_code, reachable)
        if path is not None:
            out.append(AssembledEvent(source_card_id=item.source_card_id, event=item.event, path=path))
    return out
