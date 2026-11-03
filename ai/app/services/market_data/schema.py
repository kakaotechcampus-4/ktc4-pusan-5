"""시장 데이터 한 행과 시장 맥락 결과. 숫자는 parse.py 를 거친 값이고 단위는 API 가 준 그대로다.

없는 값은 None 이다. 0 과 섞지 않는다 — 등락률 0 은 보합이고 None 은 모른다는 뜻이다.
시장 맥락(context.py) 필드는 이름 끝에 단위를 붙인다. `_pct` 는 %, `_pp` 는 %p, `_krw` 는 원이다.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


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

    @property
    def no_trades(self) -> bool:
        """그날 체결이 없었다(거래량 0). 거래정지 종목이 이렇게 온다.

        종가는 직전 가격 그대로이고 등락률은 "0.00" 이다. 보합이 아니라 거래가 없었던 것이다.
        """
        return self.volume == 0


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


class KospiComparison(BaseModel):
    """코스피와 비교. 거래정지 종목은 초과분·기여도가 None 이다(MarketContext.status_reason 참고)."""

    stock_change_rate_pct: float  # 종목 등락률 (%)
    kospi_change_rate_pct: float  # 코스피 등락률 (%). KRX 지수 응답 그대로
    excess_vs_kospi_pp: float | None  # 종목 − 코스피 (%p)
    # 코스피 내 비중 (%). 전일 시총 기준 근사다(weight_basis 참고). 보통주가 아니면 None
    kospi_weight_pct: float | None
    kospi_contribution_pp: float | None  # 코스피 기여도 (%p) = 종목 등락률 × 비중
    # 이 종목을 뺀 나머지 시장의 등락률 (%) = (코스피 − 기여도) / (1 − 비중)
    kospi_ex_self_change_rate_pct: float | None
    excess_vs_kospi_ex_self_pp: float | None  # 종목 − 자기 제외 코스피 (%p)
    # 판정에 쓴 초과분
    # kospi_ex_self  kospi_weight_pct ≥ KOSPI_EX_SELF_WEIGHT_PCT. excess_vs_kospi_ex_self_pp 로 판정한다
    # kospi          그 밖(비중이 없는 우선주 포함). excess_vs_kospi_pp 로 판정한다
    kospi_basis: Literal["kospi", "kospi_ex_self"]
    # follows   kospi_basis 초과분의 |값| ≤ KOSPI_FOLLOW_THRESHOLD_PP. 시장 흐름을 따라갔다
    # diverges  기준 초과. 시장과 크게 달랐다
    # None      초과분이 없다(대상이 거래정지)
    kospi_relation: Literal["follows", "diverges"] | None
    # 비중의 분모. 보통주 전 종목의 전일 시총 합(역산) (원)
    common_prev_market_cap_krw: int
    # 보통주 전 종목 등락률을 전일 시총으로 가중해 다시 계산한 코스피 등락률 (%).
    # 실제 코스피와 많이 다르면 보통주 판별이나 역산이 틀린 것이다
    kospi_recomputed_change_rate_pct: float
    weight_basis: str  # 비중을 어떻게 근사했는지


class PeerExclusion(BaseModel):
    """그룹 중앙값에서 뺀 구성원과 그 이유."""

    code: str
    name: str  # peer_groups.py 에 적힌 이름
    # self 대상 종목 자신 / no_trades 거래정지(거래량 0) / missing 그날 응답에 없음 / no_rate 등락률 빈 칸
    reason: Literal["self", "no_trades", "missing", "no_rate"]


class PeerComparison(BaseModel):
    """동종 그룹 하나와 비교. 그룹 등락률은 평균이 아닌 중앙값이다(시총가중 아님)."""

    group: str
    median_change_rate_pct: float | None  # 그룹 등락률 중앙값 (%). 쓸 구성원이 없으면 None
    excess_vs_group_pp: float | None  # 종목 − 그룹 중앙값 (%p). 대상이 거래정지면 None
    peer_count: int  # 중앙값에 쓴 종목 수 (= len(members_used))
    # follows      |초과분| ≤ GROUP_FOLLOW_THRESHOLD_PP. 그룹 흐름을 따라갔다
    # diverges     기준 초과이고 peer_count ≥ 2. 그룹과 크게 달랐다
    # inconclusive 기준 초과이고 peer_count 1. 차이가 비교 종목 쪽 사정일 수 있다
    # None         초과분이 없다(중앙값을 못 냈거나 대상이 거래정지)
    relation: Literal["follows", "diverges", "inconclusive"] | None
    members_used: list[str] = Field(default_factory=list)  # 중앙값에 쓴 종목 코드
    members_excluded: list[PeerExclusion] = Field(default_factory=list)


class MarketContext(BaseModel):
    """종목 하나·기준일 하나의 시장 맥락. 보고서에 넣을 숫자는 전부 여기서 계산한다.

    status
        ok               계산 완료
        no_data          기준일 KRX 데이터가 없다(당일·휴장일). kospi·peers 가 비어 있다
        stock_not_found  그날 유가증권 응답에 없는 종목이다. kospi·peers 가 비어 있다
        no_trades        거래정지(거래량 0). 초과분·기여도가 None 이고, 그룹 중앙값은 있다
    """

    bas_dd: date
    code: str
    name: str | None = None
    status: Literal["ok", "no_data", "stock_not_found", "no_trades"]
    status_reason: str | None = None
    kospi: KospiComparison | None = None
    peers: list[PeerComparison] = Field(default_factory=list)
