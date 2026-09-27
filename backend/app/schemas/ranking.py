from datetime import datetime
from typing import Literal

from pydantic import Field, FiniteFloat

from app.schemas.base import CamelModel

RankingKind = Literal["tradingValue", "volume", "gainers", "losers"]
ACTIVE_RANKINGS = ("tradingValue", "volume", "gainers", "losers")
RANKING_KINDS = ACTIVE_RANKINGS


class RankingItem(CamelModel):
    rank: int = Field(ge=1)
    code: str = Field(pattern=r"^[0-9A-Z]{6}$")
    name: str = Field(min_length=1)
    price: int = Field(ge=0, le=9007199254740991)
    change: FiniteFloat
    volume: int = Field(ge=0, le=9007199254740991)
    trading_value: int | None = Field(default=None, ge=0, le=9007199254740991)


class RankingBoard(CamelModel):
    kind: RankingKind
    status: Literal["ready", "stale", "empty", "pending", "unavailable", "notConfigured"]
    source: str = "KIS"
    # KIS 순위 응답에 거래일/체결시각이 없어 수집시각만 제공한다.
    collected_at: datetime | None = None
    items: list[RankingItem] = Field(default_factory=list)


class RankingsResponse(CamelModel):
    rankings: list[RankingBoard]
