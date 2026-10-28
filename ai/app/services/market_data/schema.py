"""시장 데이터 한 행. 숫자는 parse.py 를 거친 값이고 단위는 API 가 준 그대로다.

없는 값은 None 이다. 0 과 섞지 않는다 — 등락률 0 은 보합이고 None 은 모른다는 뜻이다.
"""

from datetime import date

from pydantic import BaseModel


class IndexDaily(BaseModel):
    """KRX 지수 일별시세 한 행 (kospi_dd_trd)."""

    bas_dd: date  # 기준일
    series: str  # 계열구분 IDX_CLSS (KRX/KOSPI/KOSDAQ)
    name: str  # 지수명 IDX_NM. 코드가 없어서 이 이름이 식별자다 ("코스피", "전기전자" …)
    close: float | None  # 종가 (지수 포인트)
    change: float | None  # 전일대비 (포인트)
    change_rate: float | None  # 등락률 (%)
    open: float | None
    high: float | None
    low: float | None
    volume: int | None  # 거래량 (주)
    trade_value: int | None  # 거래대금 (원)
    market_cap: int | None  # 상장시가총액 (원)


class StockDaily(BaseModel):
    """KRX 유가증권 종목 일별매매정보 한 행 (stk_bydd_trd)."""

    bas_dd: date
    code: str  # 단축코드 6자리. 종목기본정보 API 의 ISU_CD(ISIN 12자리)와 다르다
    name: str
    market: str  # 시장구분 MKT_NM
    close: int | None  # 종가 (원)
    change: int | None  # 전일대비 (원)
    change_rate: float | None  # 등락률 (%)
    open: int | None
    high: int | None
    low: int | None
    volume: int | None  # 거래량 (주)
    trade_value: int | None  # 거래대금 (원)
    market_cap: int | None  # 시가총액 (원)
    listed_shares: int | None  # 상장주식수 (주)


class EcosPoint(BaseModel):
    """ECOS 통계 한 시점."""

    stat_code: str  # 통계표코드
    item_code: str  # 항목코드1
    item_name: str  # 항목명1 ("원/미국달러(매매기준율)" …)
    time: str  # 시점 원문. 일 주기 "20260910", 월 주기 "202609"
    period_start: date  # 시점의 첫날. 월 주기면 그 달 1일
    value: float | None
    unit: str | None  # 단위명 ("원", "연%" …)


class ExcessMove(BaseModel):
    """종목 등락률에서 코스피 등락률을 뺀 값. 시장보다 얼마나 더(덜) 움직였나."""

    bas_dd: date
    code: str
    name: str
    stock_change_rate: float  # 종목 등락률 (%)
    index_change_rate: float  # 코스피 등락률 (%)
    excess_rate: float  # 초과분 (%p). 양수면 시장보다 더 올랐거나 덜 내렸다
