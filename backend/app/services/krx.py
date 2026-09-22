from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings
from app.schemas.market_flow import SectorItem
from app.services.market_data import Indicator, MarketDataError, Quote, number

# 종합·규모·테마 지수 및 광범위한 제조 합계는 업종 순위에서 제외한다.
SECTOR_NAMES = {
    "음식료·담배",
    "섬유·의류",
    "종이·목재",
    "화학",
    "제약",
    "비금속",
    "금속",
    "기계·장비",
    "전기전자",
    "의료·정밀기기",
    "운송장비·부품",
    "유통",
    "전기·가스",
    "건설",
    "운송·창고",
    "통신",
    "금융",
    "증권",
    "보험",
    "일반서비스",
    "오락·문화",
    "IT 서비스",
    "부동산",
    "출판·매체복제",
    "기타제조",
}


@dataclass(frozen=True)
class MarketBatch:
    quote: Quote | None
    sectors: list[SectorItem] | None
    quote_error: str | None = None
    sectors_error: str | None = None


def parse_sectors(rows: list[dict]) -> list[SectorItem]:
    items = [
        SectorItem(
            name=row["IDX_NM"],
            change=float(number(row["FLUC_RT"])),
            as_of=date.fromisoformat(row["BAS_DD"]),
        )
        for row in rows
        if row["IDX_NM"] in SECTOR_NAMES
    ]
    if (
        not items
        or len({item.name for item in items}) != len(items)
        or len({item.as_of for item in items}) != 1
    ):
        raise MarketDataError("INVALID_SECTORS")
    return sorted(items, key=lambda item: (-item.change, item.name))


async def fetch_rows(client: httpx.AsyncClient, indicator: Indicator) -> list[dict]:
    if not settings.krx_auth_key:
        raise MarketDataError("MISSING_KEY")
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    # 주말·연휴·당일 미발표를 처리한다. 인증/통신 오류는 날짜를 바꿔 재시도하지 않는다.
    for offset in range(15):
        target = today - timedelta(days=offset)
        if target.weekday() >= 5:
            continue
        response = await client.get(
            f"{settings.krx_api_base_url}/idx/{indicator.symbol}",
            headers={"AUTH_KEY": settings.krx_auth_key},
            params={"basDd": target.strftime("%Y%m%d")},
        )
        response.raise_for_status()
        body = response.json()
        if "OutBlock_1" not in body:
            raise MarketDataError("INVALID_RESPONSE")
        rows = body["OutBlock_1"]
        if any(row["IDX_NM"] == indicator.name for row in rows):
            return rows
    raise MarketDataError("NO_DATA")


def parse_quote(rows: list[dict], indicator: Indicator) -> Quote:
    for row in rows:
        if row["IDX_NM"] == indicator.name:
            return Quote(
                number(row["CLSPRC_IDX"]), number(row["FLUC_RT"]), date.fromisoformat(row["BAS_DD"])
            )
    raise MarketDataError("NO_DATA")


async def fetch_quote(client: httpx.AsyncClient, indicator: Indicator) -> Quote:
    return parse_quote(await fetch_rows(client, indicator), indicator)


async def fetch_market(client: httpx.AsyncClient, indicator: Indicator) -> MarketBatch:
    rows = await fetch_rows(client, indicator)
    # 같은 HTTP 응답을 재사용하되 한쪽 파싱 실패가 다른 쪽 정상값을 버리지 않는다.
    quote, sectors = None, None
    quote_error, sectors_error = None, None
    try:
        quote = parse_quote(rows, indicator)
    except (MarketDataError, ValueError, KeyError, TypeError, IndexError):
        quote_error = "INVALID_QUOTE"
    try:
        sectors = parse_sectors(rows)
    except (MarketDataError, ValueError, KeyError, TypeError, IndexError):
        sectors_error = "INVALID_SECTORS"
    return MarketBatch(quote, sectors, quote_error, sectors_error)
