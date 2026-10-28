"""한국은행 ECOS Open API — 원/달러 환율, 기준금리.

    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        usd = await fetch_usd_krw(client, date(2026, 9, 1), date(2026, 9, 30))
        rate = await fetch_base_rate(client, date(2026, 1, 1), date(2026, 9, 30))

    GET https://ecos.bok.or.kr/api/StatisticSearch/{키}/json/kr/{시작행}/{끝행}/{통계표}/{주기}/{시작}/{종료}/{항목}

## 키가 주소에 들어간다

**요청 주소를 로그·예외에 그대로 남기면 키가 샌다.** 그래서

    - 예외 메시지에는 키 자리를 *** 로 바꾼 주소만 넣는다. httpx 예외는 연결하지 않는다(from None).
      httpx 예외의 str 과 request 속성에 원래 주소가 들어 있다.
    - httpx 는 INFO 로 "HTTP Request: GET <주소>" 를 남긴다. 이 모듈을 불러오면 httpx 로거에
      키를 가리는 필터가 붙는다.

## 데이터 없음

기간 안에 값이 없으면 ECOS 는 `{"RESULT": {"CODE": "INFO-200", ...}}` 을 준다. 에러가 아니라 [] 다.
그 밖의 RESULT 코드(INFO-100 인증키 오류 등)는 EcosError 다.
"""

import logging
from dataclasses import dataclass
from datetime import date

import httpx

from app.core.config import settings
from app.services.market_data.errors import EcosError
from app.services.market_data.parse import to_float, to_int
from app.services.market_data.schema import EcosPoint

logger = logging.getLogger(__name__)

BASE_URL = "https://ecos.bok.or.kr/api/StatisticSearch"
MASK = "***"
NO_DATA_CODE = "INFO-200"
# 한 번에 받을 행 수. 넘으면 list_total_count 를 보고 다음 구간을 이어 받는다.
PAGE_SIZE = 1000
# 주기별 시점 형식. 이 모듈이 쓰는 주기만 둔다.
_TIME_FORMATS = {"D": "%Y%m%d", "M": "%Y%m"}


@dataclass(frozen=True)
class EcosSeries:
    stat_code: str  # 통계표코드
    cycle: str  # 주기. D(일) / M(월)
    item_code: str  # 항목코드1
    label: str


# 통계표 코드는 backend 의 ecos_client.py(feature/dart-ecos-api-client)에서 쓰던 값이다.
# 3.1.1.1 주요국 통화의 대원화환율 > 원/미국달러(매매기준율). 영업일마다 하나.
USD_KRW = EcosSeries("731Y001", "D", "0000001", "원/달러 환율")
# 1.3.1 한국은행 기준금리 및 여수신금리 > 한국은행 기준금리. 월 주기는 그 달 말 값이다.
BASE_RATE = EcosSeries("722Y001", "M", "0101000", "한국은행 기준금리")


def mask_key(text: str, key: str | None) -> str:
    """text 안의 키를 *** 로 바꾼다. 키가 비어 있으면 그대로 둔다."""
    return text.replace(key, MASK) if key else text


async def fetch_usd_krw(client: httpx.AsyncClient, start: date, end: date) -> list[EcosPoint]:
    return await fetch_series(client, USD_KRW, start, end)


async def fetch_base_rate(client: httpx.AsyncClient, start: date, end: date) -> list[EcosPoint]:
    """기준금리. 월 주기라 start·end 는 달만 본다(일은 버린다)."""
    return await fetch_series(client, BASE_RATE, start, end)


async def fetch_series(
    client: httpx.AsyncClient, series: EcosSeries, start: date, end: date
) -> list[EcosPoint]:
    """start ~ end 의 시계열. 시점 순서는 ECOS 가 준 그대로(오래된 것부터)다. 값이 없으면 []."""
    fmt = _TIME_FORMATS.get(series.cycle)
    if fmt is None:
        raise ValueError(f"지원하지 않는 주기: {series.cycle!r} (가능: {', '.join(_TIME_FORMATS)})")
    if start > end:
        raise ValueError(f"start({start}) 가 end({end}) 보다 늦다")
    key = settings.require_ecos()

    points: list[EcosPoint] = []
    first = 1
    while True:
        body = await _get(client, key, series, first, first + PAGE_SIZE - 1,
                          start.strftime(fmt), end.strftime(fmt))
        if body is None:
            return points
        rows = body.get("row") or []
        points += [_point(row, series.cycle) for row in rows]
        total = to_int(body.get("list_total_count"), field="list_total_count") or 0
        if not rows or len(points) >= total:
            return points
        first += PAGE_SIZE


async def _get(
    client: httpx.AsyncClient, key: str, series: EcosSeries,
    first: int, last: int, start: str, end: str,
) -> dict | None:
    """StatisticSearch 한 구간. INFO-200(데이터 없음)이면 None."""
    path = (f"json/kr/{first}/{last}/{series.stat_code}/{series.cycle}/"
            f"{start}/{end}/{series.item_code}")
    url = f"{BASE_URL}/{key}/{path}"
    shown = f"{BASE_URL}/{MASK}/{path}"  # 예외에 넣는 주소. 키 자리를 가렸다

    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        raise EcosError(
            f"ECOS 요청 실패 {shown}: {type(exc).__name__}: {mask_key(str(exc), key)}"
        ) from None
    if response.status_code != 200:
        raise EcosError(f"ECOS HTTP {response.status_code} {shown}")
    try:
        body = response.json()
    except ValueError:
        raise EcosError(f"ECOS JSON 이 아닌 응답 {shown}") from None
    if not isinstance(body, dict):
        raise EcosError(f"ECOS 응답 모양이 다르다 {shown}")

    if "RESULT" in body:
        result = body["RESULT"] or {}
        code, message = result.get("CODE"), mask_key(str(result.get("MESSAGE")), key)
        if code == NO_DATA_CODE:
            logger.info("ECOS %s %s~%s: 데이터 없음 (%s)", series.label, start, end, message)
            return None
        raise EcosError(f"ECOS {code}: {message} ({series.label}, {shown})")
    data = body.get("StatisticSearch")
    if not isinstance(data, dict):
        raise EcosError(f"ECOS 응답에 StatisticSearch 가 없다 {shown}")
    return data


def _point(row: dict, cycle: str) -> EcosPoint:
    time = str(row.get("TIME") or "")
    try:
        if cycle == "D":
            period_start = date(int(time[:4]), int(time[4:6]), int(time[6:8]))
        else:
            period_start = date(int(time[:4]), int(time[4:6]), 1)
    except ValueError:
        raise EcosError(f"ECOS TIME 을 날짜로 못 읽음: {time!r}") from None
    return EcosPoint(
        stat_code=row.get("STAT_CODE") or "",
        item_code=row.get("ITEM_CODE1") or "",
        item_name=row.get("ITEM_NAME1") or "",
        time=time,
        period_start=period_start,
        value=to_float(row.get("DATA_VALUE"), field="DATA_VALUE"),
        unit=row.get("UNIT_NAME"),
    )


class _MaskEcosKeyFilter(logging.Filter):
    """httpx 로그 한 줄에 ECOS 키가 들어 있으면 가린다."""

    def filter(self, record: logging.LogRecord) -> bool:
        key = (settings.ecos_api_key or "").strip()
        if key:
            message = record.getMessage()
            if key in message:
                record.msg, record.args = mask_key(message, key), ()
        return True


def _install_log_filter() -> None:
    # httpx 는 logging.getLogger("httpx") 에 직접 남긴다. 로거 필터는 그 로거에 남긴 기록에만 걸린다.
    httpx_logger = logging.getLogger("httpx")
    if not any(isinstance(f, _MaskEcosKeyFilter) for f in httpx_logger.filters):
        httpx_logger.addFilter(_MaskEcosKeyFilter())


_install_log_filter()
