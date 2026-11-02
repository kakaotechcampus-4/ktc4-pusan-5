"""외부 응답의 숫자/기준일 검증과 지표 카탈로그."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx


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
    # KRX 금시장 금 99.99_1Kg. 가격은 원/g 이다.
    Indicator("gold", "금현물", "KIS", "M04020000", "KRW/g", 60),
    Indicator("sp500", "S&P 500", "FRED", "SP500", "points", 3600),
    Indicator("nasdaq", "나스닥 종합", "FRED", "NASDAQCOM", "points", 3600),
    Indicator("usdkrw", "원/달러", "KIS", "FX@KRW", "KRW/USD", 60),
)


class MarketDataError(Exception):
    """응답 원문이나 인증키가 로그에 남지 않는 고정 오류 코드."""


def classify_upstream_error(exc: BaseException) -> str | None:
    """수집 중 난 예외를 저장용 error_code 로 분류한다.

    원인이 다르면 코드도 달라야 한다. 상태 코드는 HTTP 응답이 온 경우, 시간 초과·연결 실패는
    응답이 없는 경우, INVALID_RESPONSE 는 응답은 왔으나 해석하지 못한 경우다.
    모르는 예외는 None 을 돌려주므로 호출한 쪽에서 다시 던져 버그를 가리지 않는다.
    """
    if isinstance(exc, MarketDataError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return f"UPSTREAM_HTTP_{exc.response.status_code}"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "UPSTREAM_TIMEOUT"
    if isinstance(exc, httpx.RequestError):
        return "UPSTREAM_UNREACHABLE"
    if isinstance(exc, (ValueError, KeyError, TypeError, IndexError)):
        return "INVALID_RESPONSE"
    return None


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
