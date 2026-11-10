from datetime import date, datetime
from typing import Literal

from app.schemas.base import CamelModel


class MyScrap(CamelModel):
    scrap_id: str
    report_id: int
    # 지금은 STOCK 만. 시장 보고서가 생기면 MARKET 을 더한다.
    report_type: Literal["STOCK"] = "STOCK"
    stock_code: str
    stock_name: str | None = None
    # 보고서 당시 등락률(%). 현재가 기준이 아니다.
    change_pct: float | None = None
    as_of: datetime
    target_date: date | None = None
    # 한 줄 요약. LLM 생성물이다.
    headline: str | None = None
    generated_at: datetime | None = None
    sources: list[str]
    scrapped_at: datetime


class MyScrapList(CamelModel):
    # scrapped_at 내림차순
    items: list[MyScrap]
