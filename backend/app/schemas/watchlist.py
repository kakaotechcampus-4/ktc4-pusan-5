from datetime import datetime
from typing import Literal

from pydantic import Field, FiniteFloat

from app.schemas.base import CamelModel


class WatchlistAddRequest(CamelModel):
    stock_code: str = Field(pattern=r"^[0-9A-Z]{6}$")


class WatchlistQuote(CamelModel):
    price: FiniteFloat
    change: FiniteFloat
    change_amount: FiniteFloat


class WatchlistEntry(CamelModel):
    code: str
    name: str
    market: Literal["KOSPI", "KOSDAQ"]
    # 시세 수집 전이면 None
    quote: WatchlistQuote | None = None
    as_of: datetime | None = None


class WatchlistResponse(CamelModel):
    items: list[WatchlistEntry]
