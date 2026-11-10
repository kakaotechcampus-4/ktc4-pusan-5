"""종목 변동 요인 보고서 HTTP 계약. 보고서는 ai 파이프라인이 만들어 DB 에 적재한다.

응답에 넣지 않는 것:
- `quote`(텔레그램 원문 인용): 이용 권한이 확인되지 않아 내보내지 않는다.
- `not_found`·`events`·`issue_trace`: 검수용이라 화면에 나가지 않는다.
"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel

Verdict = Literal["explained", "partially_explained", "no_clear_cause"]
Stance = Literal["bullish", "bearish", "neutral"]
Layer = Literal["move", "relative"]
Strength = Literal["sufficient", "partial", "insufficient"]
Match = Literal["direct", "indirect"]


class ReportSource(CamelModel):
    channel: str | None = None
    url: str | None = None
    datetime_kst: datetime | None = None
    match: Match | None = None
    is_market_recap: bool | None = None


class ReportLink(CamelModel):
    """사건 하나가 어느 층(등락·상대)의 질문에 어떻게 답하는가."""

    layer: Layer
    note: str | None = None
    direction_match: bool | None = None
    strength: Strength | None = None


class ReportFactor(CamelModel):
    event: str
    detail: str = ""
    stance: Stance | None = None
    unconfirmed: bool = False
    links: list[ReportLink] = Field(default_factory=list)
    sources: list[ReportSource] = Field(default_factory=list)


class ReportTerm(CamelModel):
    plain: str
    term: str
    # 개념 글에 같은 용어가 있으면 그 slug. 화면이 `/concepts/{slug}` 로 연결한다.
    concept_slug: str | None = None


class BackgroundItem(CamelModel):
    text: str
    sources: list[ReportSource] = Field(default_factory=list)
    watch: bool | None = None


class ReportBackground(CamelModel):
    bullish: list[BackgroundItem] = Field(default_factory=list)
    bearish: list[BackgroundItem] = Field(default_factory=list)
    neutral: list[BackgroundItem] = Field(default_factory=list)


class ReportSummary(CamelModel):
    move: str | None = None
    main_cause: str | None = None
    relative: str | None = None
    counter: str | None = None
    unexplained: str | None = None


class StockReport(CamelModel):
    id: int
    code: str
    name: str | None = None
    as_of: datetime
    change_pct: float | None = None
    # LLM 생성물이라 생성 시각을 반드시 싣는다(루트 CLAUDE.md API 규약). 모르면 null.
    generated_at: datetime | None = None
    verdict: Verdict
    relative_verdict: Verdict | None = None
    summary: ReportSummary
    factors: list[ReportFactor] = Field(default_factory=list)
    terms: list[ReportTerm] = Field(default_factory=list)
    background: ReportBackground


class ReportListItem(CamelModel):
    """보고서 목록(홈) 한 줄. 눌러서 종목 상세로 가므로 본문은 싣지 않는다."""

    id: int
    code: str
    name: str | None = None
    as_of: datetime
    change_pct: float | None = None
    generated_at: datetime | None = None
    verdict: Verdict
    # 한 줄 요약. LLM 생성물이다.
    headline: str | None = None


class ReportList(CamelModel):
    items: list[ReportListItem]
