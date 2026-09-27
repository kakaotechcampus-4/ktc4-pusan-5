"""외부 응답의 숫자/기준일 검증과 지표 카탈로그."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Indicator:
    code: str
    name: str
    source: str | None
    symbol: str
    unit: str | None
    interval: int


INDICATORS = (
    Indicator("kospi", "코스피", "KRX", "kospi_dd_trd", "points", 3600),
    Indicator("kosdaq", "코스닥", "KRX", "kosdaq_dd_trd", "points", 3600),
    Indicator("gold", "금현물", None, "", None, 0),
    Indicator("sp500", "S&P 500", "FRED", "SP500", "points", 3600),
    Indicator("nasdaq", "나스닥 종합", "FRED", "NASDAQCOM", "points", 3600),
    Indicator("usdkrw", "원/달러", "KIS", "FX@KRW", "KRW/USD", 60),
)


class MarketDataError(Exception):
    """응답 원문이나 인증키가 로그에 남지 않는 고정 오류 코드."""


def number(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw).replace(",", ""))
    except InvalidOperation:
        raise MarketDataError("INVALID_RESPONSE") from None
    if not value.is_finite() or abs(value) >= Decimal("1e16"):
        raise MarketDataError("INVALID_RESPONSE")
    return value


@dataclass(frozen=True)
class Quote:
    value: Decimal
    change: Decimal
    observation_date: date

    def __post_init__(self):
        if self.value <= 0:
            raise MarketDataError("INVALID_RESPONSE")
