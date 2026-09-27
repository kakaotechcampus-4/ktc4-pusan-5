"""종목 상세 HTTP 계약. 원천 시각과 수집 시각은 별개다."""

from datetime import date, datetime
from typing import Literal, TypeVar

from pydantic import Field, FiniteFloat

from app.schemas.base import CamelModel

Period = Literal["1M", "3M", "1Y", "5Y", "ALL"]
T = TypeVar("T")


class Resource[T](CamelModel):
    status: Literal["pending", "ready", "stale", "unavailable", "empty"]
    refreshing: bool = False
    data: T | None = None
    source_as_of: datetime | None = None
    collected_at: datetime | None = None
    retry_after_seconds: int | None = None


class StockIdentity(CamelModel):
    code: str
    name: str
    market: Literal["KOSPI", "KOSDAQ"]
    listing_status: Literal["listed", "inactive"]
    listed_at: date | None = None


class QuoteData(CamelModel):
    price: FiniteFloat = Field(gt=0)
    change: FiniteFloat
    change_amount: FiniteFloat
    volume: int = Field(ge=0, le=9007199254740991)
    trading_value: FiniteFloat = Field(ge=0)
    market_cap: FiniteFloat | None = Field(default=None, ge=0)


class MetricsData(CamelModel):
    per: FiniteFloat | None = None
    pbr: FiniteFloat | None = None
    eps: FiniteFloat | None = None
    bps: FiniteFloat | None = None
    foreign_ownership: FiniteFloat | None = Field(default=None, ge=0, le=100)
    week52_high: FiniteFloat | None = Field(default=None, ge=0)
    week52_low: FiniteFloat | None = Field(default=None, ge=0)


class Candle(CamelModel):
    date: date
    open: FiniteFloat
    high: FiniteFloat
    low: FiniteFloat
    close: FiniteFloat
    volume: int


class StockOverview(CamelModel):
    stock: StockIdentity
    quote: Resource[QuoteData]
    metrics: Resource[MetricsData]


class Coverage(CamelModel):
    from_date: date
    to_date: date
    complete: bool


class StockPrices(Resource[list[Candle]]):
    code: str
    period: Period
    adjustment: Literal["raw"] = "raw"
    coverage: Coverage
