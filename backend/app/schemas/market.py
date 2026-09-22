from datetime import date, datetime
from typing import Literal

from pydantic import FiniteFloat

from app.schemas.base import CamelModel
from app.schemas.market_flow import FlowBoard, SectorBoard
from app.schemas.ranking import RankingBoard


class MarketItem(CamelModel):
    code: str
    name: str
    source: str | None
    unit: Literal["points", "KRW/USD"] | None
    status: Literal["ready", "stale", "unavailable", "pending", "notConfigured"]
    value: FiniteFloat | None = None
    change: FiniteFloat | None = None
    # 원천에서 날짜만 제공하므로 시각을 임의로 붙이지 않는다.
    as_of: date | None = None
    collected_at: datetime | None = None


class MarketOverview(CamelModel):
    items: list[MarketItem]
    rankings: list[RankingBoard]
    flows: list[FlowBoard]
    sectors: list[SectorBoard]
