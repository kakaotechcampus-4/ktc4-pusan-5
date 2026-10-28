"""KRX Open API — 코스피 지수 일별시세, 유가증권 종목 일별매매정보.

    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        kospi = await fetch_kospi(client, date(2026, 9, 10))
        stock = await fetch_stock(client, date(2026, 9, 10), "005930")

요청 형식은 팀 조사(backend/docs/api-research/krx.md, 2026-09-11 실호출)를 따른다.

    POST https://data-dbg.krx.co.kr/svc/apis{경로}
    헤더  AUTH_KEY: <키>, Content-Type: application/json
    본문  {"basDd": "YYYYMMDD"}

Content-Type 이 빠지면 200 인데 결과가 항상 빈 배열이다. 휴장일 응답과 구분이 안 되므로 꼭 보낸다.

## 빈 결과

**일별 확정 데이터라 당일 데이터는 없다(최소 T+1).** 휴장일, 미래 날짜, 형식이 틀린 날짜도
전부 `200 {"OutBlock_1": []}` 로 온다. 응답만 보고는 이유를 가릴 수 없다. 그래서

    - 날짜는 date 로만 받는다. 형식이 틀려서 빈 배열이 오는 경우를 없앤다.
    - 빈 배열은 예외 없이 빈 결과([] 또는 None)로 돌려주고 로그를 남긴다.

**인증 실패만 에러로 구분된다.** 같은 401 이라도 respMsg 가 다르다.

    "Unauthorized Key"       키가 틀렸거나 헤더가 없다
    "Unauthorized API Call"  키는 맞는데 이 API 의 이용신청이 안 됐다
"""

import logging
from datetime import date

import httpx

from app.core.config import settings
from app.services.market_data.errors import KrxAuthError, KrxError
from app.services.market_data.parse import to_float, to_int
from app.services.market_data.schema import IndexDaily, StockDaily

logger = logging.getLogger(__name__)

BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
KOSPI_INDEX_PATH = "/idx/kospi_dd_trd"  # KOSPI 시리즈 일별시세 (종합지수 + 업종지수)
KOSPI_STOCK_PATH = "/sto/stk_bydd_trd"  # 유가증권 일별매매정보
# kospi_dd_trd 에서 종합지수 행의 IDX_NM. 첫 행 "코스피 (외국주포함)" 는 가격 칸이 비어 있어 쓰지 않는다.
KOSPI_INDEX_NAME = "코스피"
# 오류 메시지에 응답 본문은 이만큼만 남긴다.
ERROR_BODY_MAX_CHARS = 200


async def fetch_kospi_index_daily(client: httpx.AsyncClient, bas_dd: date) -> list[IndexDaily]:
    """kospi_dd_trd 전체 행(종합지수 + 업종지수). 데이터가 없는 날은 []."""
    rows = await _post(client, KOSPI_INDEX_PATH, bas_dd)
    return [_index_row(row) for row in rows]


async def fetch_kospi(client: httpx.AsyncClient, bas_dd: date) -> IndexDaily | None:
    """코스피 종합지수 한 행. 데이터가 없는 날은 None."""
    for index in await fetch_kospi_index_daily(client, bas_dd):
        if index.name == KOSPI_INDEX_NAME:
            return index
    return None


async def fetch_stock_daily(client: httpx.AsyncClient, bas_dd: date) -> list[StockDaily]:
    """유가증권 전 종목. 하루치가 한 응답에 다 온다(900여 건, 1~2초). 데이터가 없는 날은 []."""
    rows = await _post(client, KOSPI_STOCK_PATH, bas_dd)
    return [_stock_row(row) for row in rows]


async def fetch_stock(client: httpx.AsyncClient, bas_dd: date, code: str) -> StockDaily | None:
    """종목 하나(단축코드 6자리). 그날 데이터가 없거나 유가증권 종목이 아니면 None.

    KRX 에는 종목 하나만 묻는 API 가 없다. 전 종목을 받아서 고른다.
    여러 종목을 볼 때는 fetch_stock_daily 를 한 번 부르고 거기서 고른다.
    """
    for stock in await fetch_stock_daily(client, bas_dd):
        if stock.code == code:
            return stock
    return None


async def _post(client: httpx.AsyncClient, path: str, bas_dd: date) -> list[dict]:
    if not isinstance(bas_dd, date):
        # "2026-09-10" 같은 문자열을 넘기면 KRX 는 에러 대신 빈 배열을 준다. 휴장일로 오인한다.
        raise TypeError(f"bas_dd 는 date 여야 한다: {bas_dd!r}")
    basdd = bas_dd.strftime("%Y%m%d")
    try:
        response = await client.post(
            f"{BASE_URL}{path}",
            headers={"AUTH_KEY": settings.require_krx(), "Content-Type": "application/json"},
            json={"basDd": basdd},
        )
    except httpx.HTTPError as exc:
        raise KrxError(f"KRX {path} {basdd} 요청 실패: {type(exc).__name__}: {exc}") from exc

    if response.status_code == 401:
        message = _resp_msg(response)
        if message == "Unauthorized API Call":
            raise KrxAuthError(
                f"KRX {path}: 이 API 의 이용신청이 안 됐다. openapi.krx.co.kr 에서 API 별로 신청한다."
            )
        raise KrxAuthError(f"KRX {path}: 인증키가 틀렸다 ({message or '응답 메시지 없음'}). KRX_AUTH_KEY 를 확인한다.")
    if response.status_code != 200:
        raise KrxError(
            f"KRX {path} {basdd}: HTTP {response.status_code} {response.text[:ERROR_BODY_MAX_CHARS]}"
        )

    try:
        body = response.json()
    except ValueError:
        raise KrxError(
            f"KRX {path} {basdd}: JSON 이 아닌 응답 {response.text[:ERROR_BODY_MAX_CHARS]!r}"
        ) from None
    rows = body.get("OutBlock_1") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise KrxError(f"KRX {path} {basdd}: 응답에 OutBlock_1 이 없다 {str(body)[:ERROR_BODY_MAX_CHARS]}")
    if not rows:
        logger.info("KRX %s %s: 데이터 없음 (당일·휴장일이거나 아직 확정 전)", path, basdd)
    return rows


def _resp_msg(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("respMsg") if isinstance(body, dict) else None


def _bas_dd(value: str) -> date:
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except (TypeError, ValueError):
        raise KrxError(f"BAS_DD 를 날짜로 못 읽음: {value!r}") from None


def _index_row(row: dict) -> IndexDaily:
    return IndexDaily(
        bas_dd=_bas_dd(row.get("BAS_DD")),
        series=row.get("IDX_CLSS") or "",
        name=row.get("IDX_NM") or "",
        close=to_float(row.get("CLSPRC_IDX"), field="CLSPRC_IDX"),
        change=to_float(row.get("CMPPREVDD_IDX"), field="CMPPREVDD_IDX"),
        change_rate=to_float(row.get("FLUC_RT"), field="FLUC_RT"),
        open=to_float(row.get("OPNPRC_IDX"), field="OPNPRC_IDX"),
        high=to_float(row.get("HGPRC_IDX"), field="HGPRC_IDX"),
        low=to_float(row.get("LWPRC_IDX"), field="LWPRC_IDX"),
        volume=to_int(row.get("ACC_TRDVOL"), field="ACC_TRDVOL"),
        trade_value=to_int(row.get("ACC_TRDVAL"), field="ACC_TRDVAL"),
        market_cap=to_int(row.get("MKTCAP"), field="MKTCAP"),
    )


def _stock_row(row: dict) -> StockDaily:
    return StockDaily(
        bas_dd=_bas_dd(row.get("BAS_DD")),
        code=row.get("ISU_CD") or "",
        name=row.get("ISU_NM") or "",
        market=row.get("MKT_NM") or "",
        close=to_int(row.get("TDD_CLSPRC"), field="TDD_CLSPRC"),
        change=to_int(row.get("CMPPREVDD_PRC"), field="CMPPREVDD_PRC"),
        change_rate=to_float(row.get("FLUC_RT"), field="FLUC_RT"),
        open=to_int(row.get("TDD_OPNPRC"), field="TDD_OPNPRC"),
        high=to_int(row.get("TDD_HGPRC"), field="TDD_HGPRC"),
        low=to_int(row.get("TDD_LWPRC"), field="TDD_LWPRC"),
        volume=to_int(row.get("ACC_TRDVOL"), field="ACC_TRDVOL"),
        trade_value=to_int(row.get("ACC_TRDVAL"), field="ACC_TRDVAL"),
        market_cap=to_int(row.get("MKTCAP"), field="MKTCAP"),
        listed_shares=to_int(row.get("LIST_SHRS"), field="LIST_SHRS"),
    )
