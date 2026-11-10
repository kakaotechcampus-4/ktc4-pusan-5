"""입력 market_compare 칸. 시장 맥락(market_data.context)을 프롬프트 1부 입력 형식으로 옮긴다.

    compare_for = MarketCompare(client)                  # 실행 하나에 하나
    payload, fields = await compare_for.apply(payload)   # 모델에 보낼 입력, 래퍼에 남길 칸

러너가 보고서마다 입력에 넣는다(collectors.stock_analysis). 입력에 같은 칸이 있어도 다시 계산해 덮어쓴다 —
market 계산 칸과 같이 계산은 한 곳에서만 한다.

## 기준 시각이 장 마감 전이면 넣지 않는다

KRX 는 장 마감 확정 데이터만 있다. cutoff 가 target_date 의 장 마감(market_close — 평소 MARKET_CLOSE 15:30 KST,
LATE_CLOSE 에 있는 날은 그 시각)보다 이르면 그날 종가는 기준 시각 뒤의 일이라 모델에 보여 주면 안 된다. KRX 를 부르지 않고 칸을 null 로 둔다(래퍼 market_compare_skipped
BEFORE_CLOSE). 입력 change_pct 는 기준 시각의 값이라 그대로 쓴다.

## 장 마감 이후 ok 면 입력 등락률을 KRX 로 바꾼다

입력 change_pct 와 KRX 등락률은 출처가 달라 어긋날 수 있다. 한 입력에 두 숫자가 있으면 모델이 어느 쪽을 쓸지
모른다. 그래서 시장 맥락이 ok 면 change_pct 를 KRX 등락률(market_compare.kospi.stock_change_rate_pct)로 덮어쓴다.
그 밖(no_data·실패·no_trades·stock_not_found)은 입력 값을 그대로 쓴다.

입력 market 의 대형주 비교 수치(peer_median_pct·peer_up·peer_down·peer_total)도 입력을 만든 쪽 시세라, 같이 바꾸지
않으면 excess_pct(= change_pct − peer_median_pct)가 두 출처를 섞는다. 입력에 peer_median_pct 가 있으면 이미 받아 둔
KRX 전 종목 응답으로 대형주 유니버스(stock_meta.universe_codes) 중간값과 상승·하락·전체 수를 다시 계산하고
excess_pct 도 다시 계산한다(universe_peers). 대상 종목 자신과 응답에 없는·거래정지·등락률 빈 칸 종목은 뺀다.
쓸 종목이 하나도 없으면 대형주 비교 수치와 excess_pct 를 null 로 둔다 — 입력 중간값으로 excess_pct 를 내면
종목은 KRX, 대형주는 입력 시세라 다시 두 출처가 섞인다. 키는 남겨 프롬프트 1부 스키마("없으면 null")와 맞추고,
생성·검증은 null 이면 대형주 비교를 하지 않는다. 원래 값·다시 계산한 값(null 로 뒀으면 krx·recomputed 가 null)·뺀
종목은 래퍼 change_pct_override 에 남는다. 입력에 peer_median_pct 가 없으면 대형주 비교 수치는 건드리지 않는다(없던 비교를 켜지 않는다).

입력 market 이 null 이면(분류 어댑터 입력) 위 칸을 모두 KRX 로 새로 만든다 — 지수 "코스피"·KRX 코스피 등락률·장 마감
시각, 대형주 비교 수치(universe_peers)와 excess_pct, url 은 "". 안 만들면 market.excess_pct 로 판단하는 상대 층과
summary.move 의 비교 문장이 꺼진다. 원래 null 이었다는 건 래퍼 change_pct_override.market_created 에 남는다. 장 마감
전·실패·ok 가 아닌 status 면 null 그대로다.

입력 market 의 지수 등락률(change_pct)·as_of 도 같은 이유로 KRX 코스피 등락률(market_compare.kospi.kospi_change_rate_pct)과
그날 장 마감 시각으로 바꾼다. 안 바꾸면 모델 입력에 출처·시각이 다른 코스피 등락률이 둘 있고, 정형 보고서 move 문장도 입력
값을 쓴다. 입력 지수 등락률이 숫자가 아니면(null·칸 없음) 건드리지 않는다. 원래 값은 change_pct_override.index 에 남는다.

## KRX 는 기준일마다 한 번

fetch_market_context 는 부를 때마다 KRX 를 두 번 부른다(코스피 지수, 유가증권 전 종목 900여 건). 같은 날
보고서가 여럿이면 같은 응답을 종목 수만큼 받게 된다. 그래서 그 함수를 쓰지 않고, 기준일마다 두 응답을 한 번
받아 두고 종목마다 build_market_context 만 부른다. 같은 날 보고서가 동시에 들어와도 기준일마다 Task 하나를
함께 기다리므로 호출은 한 번이다. **실패도 기준일마다 한 번만 시도하고 로그도 한 번만
남긴다** — 그 날 보고서는 모두 같은 사유로 비교 없이 만든다. 같은 실행 안에서 다시 시도하지 않는다.

기준일 Task 는 asyncio.shield 로 기다린다. 보고서 하나가 취소돼도 그 보고서만 멈추고, 같은 날 다른 보고서가 함께 기다리는
Task 는 취소되지 않는다.

## KRX 를 못 읽어도 보고서는 만든다

호출·계산이 실패하면 칸을 null 로 두고 사유를 돌려준다(래퍼 market_compare_error). 기준일 데이터가 없으면
status 가 no_data 인 칸이 그대로 간다. 어느 쪽이든 프롬프트 3단계 「비교 수치」가 코스피·그룹 비교 문장을 쓰지
않게 한다. 나머지 보고서는 그대로 만든다.

**어떤 예외든 여기서 멈춘다.** 시장 맥락은 보고서의 곁가지라 이 때문에 실행 전체(asyncio.gather)가 멈추면 안 된다.
KRX 응답 처리에서 난 예외는 그 날짜의 실패(같은 날 보고서 모두), 종목별 계산·입력 덮어쓰기에서 난 예외는 그 보고서의
실패다. 대신 묻히지 않게 예외 종류를 래퍼(market_compare_error_type)와 러너 요약에 남긴다. 예상한 실패
(EXPECTED_ERRORS — KRX 호출 실패·응답 깨짐·키 없음은 RuntimeError, 등락률 빈 칸·보통주 0개는 ValueError)가 아니면
market_compare_unexpected 를 켜고 traceback 과 함께 ERROR 로그를 남긴다. 코드 버그나 KRX 응답 모양 변화다.

프롬프트 1부에 적힌 칸만 보낸다. 비중의 분모·재계산 코스피·weight_basis 는 검수용이라 모델에 보내지 않는다.
members_used 는 코드만 있어서 그룹 정의(peer_groups)에서 이름을 붙인다.
"""

import asyncio
import functools
import logging
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import httpx

from app.repositories.stock_move_analysis import KST
from app.services.market_data import (
    GROUPS,
    IndexDaily,
    MarketContext,
    StockDaily,
    build_market_context,
    fetch_kospi,
    fetch_stock_daily,
)
from app.services.market_data.krx import KOSPI_INDEX_NAME, KOSPI_INDEX_PATH, KOSPI_STOCK_PATH
from app.services.stock_analysis.stock_meta import universe_codes

logger = logging.getLogger(__name__)

# 유가증권시장 정규장 마감(KST). cutoff 가 target_date 의 이 시각과 같거나 늦으면 KRX 종가 데이터를 쓴다.
MARKET_CLOSE = time(15, 30)
# 장 마감이 늦춰지는 날(수능일 등)과 그날 마감 시각(KST). 매년 추가 필요 — 거래소 공지가 나오면 넣는다.
# 규칙이 아니라 날짜 목록이라, 그해 날짜가 하나도 없으면 market_close 가 WARNING 을 남긴다(연도마다 한 번).
LATE_CLOSE = {
    date(2026, 11, 19): time(16, 30),  # 2027학년도 수능
}
# 래퍼 market_compare_skipped 값. 기준 시각이 장 마감 전이라 시장 맥락을 넣지 않았다.
BEFORE_CLOSE = "BEFORE_CLOSE"
# 결과(ok)를 KRX 등락률로 덮어쓸 수 있는 status. no_trades 의 0.00 은 보합이 아니라 거래가 없던 것이라 쓰지 않는다.
OVERRIDE_STATUS = "ok"
# 다시 계산한 중간값·excess_pct 의 자리 수. 입력 등락률과 같은 소수 둘째 자리.
RATE_DECIMALS = 2
# 예상한 실패. MarketDataError(KRX 호출 실패·응답 깨짐)·키 없음은 RuntimeError, 등락률 빈 칸·보통주 0개는 ValueError 다.
# 이 밖의 예외도 잡지만 예상 밖(market_compare_unexpected)으로 표시한다.
EXPECTED_ERRORS = (RuntimeError, ValueError)

# 프롬프트 1부 market_compare.kospi 의 칸. 순서도 프롬프트와 같다.
KOSPI_KEYS = (
    "stock_change_rate_pct",
    "kospi_change_rate_pct",
    "excess_vs_kospi_pp",
    "kospi_weight_pct",
    "kospi_contribution_pp",
    "kospi_ex_self_change_rate_pct",
    "excess_vs_kospi_ex_self_pp",
    "kospi_basis",
    "kospi_relation",
)

Day = tuple[IndexDaily | None, list[StockDaily]]


@dataclass(frozen=True)
class CompareFailure:
    """시장 맥락 실패 하나. str 은 래퍼 market_compare_error 에 남기는 "<예외 이름>: <메시지>" 다."""

    kind: str  # 예외 이름 (KrxError, AttributeError …)
    message: str
    unexpected: bool  # EXPECTED_ERRORS 밖의 예외

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"


def _failure(exc: Exception, stage: str, subject: str) -> CompareFailure:
    """예외를 실패로 바꾸고 로그를 남긴다. 예상 밖이면 traceback 과 함께 ERROR 다. subject 는 "<종목> <기준일>" 이나
    기준일 전체의 실패면 "<기준일> 전체"."""
    failure = CompareFailure(type(exc).__name__, str(exc), not isinstance(exc, EXPECTED_ERRORS))
    if failure.unexpected:
        logger.error("시장 맥락 %s 에서 예상 밖 예외, 비교 없이 만든다 (%s): %s", stage, subject, failure, exc_info=exc)
    else:
        logger.warning("시장 맥락을 못 읽어 비교 없이 만든다 (%s): %s", subject, failure)
    return failure


class MarketCompare:
    """실행 하나의 market_compare 칸을 만든다. 기준일별 KRX 응답을 실행이 끝날 때까지 들고 있는다."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._days: dict[date, asyncio.Task[Day | CompareFailure]] = {}

    async def apply(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """(모델에 보낼 입력, 래퍼에 남길 칸). 받은 payload 는 바꾸지 않는다. 예외를 올리지 않는다.

        래퍼 칸: market_compare(보낸 칸), market_compare_error(칸이 null 인 실패 사유)·market_compare_error_type
        (예외 이름)·market_compare_unexpected(예상 밖 예외인가), market_compare_skipped(장 마감 전이면 BEFORE_CLOSE),
        change_pct_override(KRX 로 덮어썼으면 원래 값과 출처).
        """
        fields: dict[str, Any] = {"market_compare": None, "market_compare_error": None,
                                  "market_compare_error_type": None, "market_compare_unexpected": False,
                                  "market_compare_skipped": None, "change_pct_override": None}
        if not after_close(payload):
            fields["market_compare_skipped"] = BEFORE_CLOSE
            return {**payload, "market_compare": None}, fields
        compare, failure = await self(payload)
        out = {**payload, "market_compare": compare}
        if compare is not None and compare["status"] == OVERRIDE_STATUS:
            try:
                _, stocks = await self._days[date.fromisoformat(payload["target_date"])]  # 이미 끝난 Task 다
                out, fields["change_pct_override"] = override_change_pct(out, compare, stocks)
            # 덮어쓰지 못했는데 칸만 보내면 입력 등락률과 KRX 등락률이 섞인다. 시장 맥락 전체를 실패로 돌린다
            except Exception as exc:  # noqa: BLE001 — 시장 맥락 때문에 실행이 멈추면 안 된다. 종류는 래퍼에 남긴다
                failure = _failure(exc, "입력 덮어쓰기", f"{payload['code']} {payload['target_date']}")
                compare, out = None, {**payload, "market_compare": None}
        fields["market_compare"] = compare
        if failure is not None:
            fields.update(market_compare_error=str(failure), market_compare_error_type=failure.kind,
                          market_compare_unexpected=failure.unexpected)
        return out, fields

    async def __call__(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, CompareFailure | None]:
        """(입력 칸, 실패). 실패하면 (None, 실패), 아니면 (칸, None). 예외를 올리지 않는다."""
        code, target_date = payload["code"], payload["target_date"]
        day = date.fromisoformat(target_date)
        if day not in self._days:
            self._days[day] = asyncio.create_task(self._fetch(day))
        # 이 보고서가 취소돼도 같은 날 다른 보고서가 기다리는 Task 는 취소하지 않는다
        fetched = await asyncio.shield(self._days[day])
        # 그 날짜의 실패다. 같은 날 보고서는 모두 같은 실패를 받는다. 로그는 _fetch 가 한 번 남겼다
        if isinstance(fetched, CompareFailure):
            return None, fetched
        kospi, stocks = fetched
        try:
            return to_input(build_market_context(str(code), day, kospi, stocks)), None
        # 그 종목의 실패다. 같은 날 다른 종목은 계산한다
        except Exception as exc:  # noqa: BLE001 — 시장 맥락 때문에 실행이 멈추면 안 된다. 종류는 래퍼에 남긴다
            return None, _failure(exc, "계산", f"{code} {target_date}")

    async def _fetch(self, day: date) -> Day | CompareFailure:
        """fetch_market_context 와 같은 두 호출. 코스피가 없는 날은 전 종목을 부르지 않는다.
        실패하면 예외 대신 실패를 돌려준다. 같은 날 보고서마다 다시 올리면 로그가 보고서 수만큼 남는다."""
        try:
            kospi = await fetch_kospi(self._client, day)
            stocks = await fetch_stock_daily(self._client, day) if kospi is not None else []
        except Exception as exc:  # noqa: BLE001 — 시장 맥락 때문에 실행이 멈추면 안 된다. 종류는 래퍼에 남긴다
            return _failure(exc, "KRX 응답 처리", f"{day.isoformat()} 전체")
        return kospi, stocks


def market_close(day: date) -> time:
    """그날 장 마감 시각(KST). LATE_CLOSE 에 있으면 그 시각, 아니면 MARKET_CLOSE."""
    _warn_if_late_close_missing(day.year)
    return LATE_CLOSE.get(day, MARKET_CLOSE)


@functools.cache
def _warn_if_late_close_missing(year: int) -> None:
    """LATE_CLOSE 에 그해 날짜가 하나도 없으면 WARNING. 넣는 걸 잊으면 수능일도 15:30 마감으로 보고 장중 값을 종가로
    쓰게 된다. 날짜는 거래소 공지로만 알 수 있어 추측해 넣지 않는다. 연도마다 한 번만 남긴다(functools.cache)."""
    if not any(day.year == year for day in LATE_CLOSE):
        logger.warning("LATE_CLOSE 에 %d년 날짜가 없다. 수능일 등 장 마감이 늦춰지는 날을 거래소 공지대로 넣는다"
                       "(넣지 않으면 그날도 %s 마감으로 본다)", year, MARKET_CLOSE.strftime("%H:%M"))


def after_close(payload: dict[str, Any]) -> bool:
    """cutoff 가 target_date 의 장 마감(market_close, KST)과 같거나 늦은가. 다음 날 새벽 같은 기준 시각도 장 마감 이후다."""
    cutoff = datetime.fromisoformat(payload["cutoff"])
    day = date.fromisoformat(payload["target_date"])
    return cutoff >= datetime.combine(day, market_close(day), tzinfo=KST)


def display_as_of(payload: dict[str, Any]) -> tuple[datetime, bool] | None:
    """화면·독자 문장의 기준 시각 (KST aware datetime, 장 마감 기준인가). 표시 시각은 여기서만 정한다.

    장 마감 이후(after_close)면 target_date 의 market_close 다. 다음 날 08:30 에 돌린 입력이어도 보고서가 설명하는 건
    target_date 장 마감까지의 움직임이라 "오전 8시 30분 기준" 이 아니라 "오후 3시 30분 장 마감 기준" 이다. 장 마감이
    늦춰지는 날(LATE_CLOSE)은 그 시각이 장 마감이다. 장중이면 cutoff 시각이다. cutoff·target_date 를 못 읽으면 None.

    보고서 as_of 는 이 값이 아니라 입력 cutoff(메시지를 자른 시각) 그대로다 — 적재 자연키와 출처 시각 대조가 그 시각을
    본다(finalize.fix_as_of).
    """
    try:
        day = date.fromisoformat(payload["target_date"])
        if after_close(payload):
            return datetime.combine(day, market_close(day), tzinfo=KST), True
        return datetime.fromisoformat(payload["cutoff"]).astimezone(KST), False
    except (KeyError, TypeError, ValueError):
        return None


def override_change_pct(
    payload: dict[str, Any], compare: dict[str, Any], stocks: list[StockDaily],
    universe: Iterable[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(change_pct 를 KRX 등락률로 바꾼 입력, 래퍼 change_pct_override).

    입력 market 에 지수 등락률(change_pct)이 있으면 KRX 코스피 등락률과 그날 장 마감 시각(as_of)으로 바꾼다.
    peer_median_pct 가 있으면 대형주 비교 수치를 stocks(같은 날 KRX 전 종목)로 다시 계산하고 excess_pct 도 다시
    계산한다. 쓸 유니버스 종목이 없으면(universe_peers 가 None) 대형주 비교 수치와 excess_pct 를 null 로 둔다.
    universe 를 안 주면 stock_meta 의 대형주 유니버스다.

    입력 market 이 null 이면(분류 어댑터 입력) 지수·대형주 비교 칸을 모두 KRX 로 새로 만든다. 래퍼
    market_created 가 true 다. 쓸 대형주가 없으면 peer_*·excess_pct 는 null 이다(위와 같다).
    """
    krx = compare["kospi"]["stock_change_rate_pct"]
    out = {**payload, "change_pct": krx}
    record: dict[str, Any] = {
        "input": payload["change_pct"], "krx": krx,
        "source": f"KRX {KOSPI_STOCK_PATH} {payload['target_date']} FLUC_RT",
        "market_created": False, "index": None, "peers": None, "excess_pct": None,
    }
    market = payload.get("market")
    created = market is None
    if created:
        market = {"index": KOSPI_INDEX_NAME, "change_pct": None, "as_of": None, "url": "",
                  **dict.fromkeys(PEER_KEYS), "excess_pct": None}
        record["market_created"] = True
    if not isinstance(market, dict):
        return out, record
    new_market = dict(market)
    if created or _is_rate(market.get("change_pct")):
        index = {"change_pct": compare["kospi"]["kospi_change_rate_pct"],
                 "as_of": market_close(date.fromisoformat(payload["target_date"])).strftime("%H:%M")}
        new_market.update(index)
        record["index"] = {"input": {"change_pct": market["change_pct"], "as_of": market.get("as_of")}, "krx": index,
                           "source": f"KRX {KOSPI_INDEX_PATH} {payload['target_date']} {KOSPI_INDEX_NAME} FLUC_RT"}
    if created or _is_rate(market.get("peer_median_pct")):
        peers, excluded = universe_peers(stocks, str(payload["code"]),
                                         universe_codes() if universe is None else universe)
        record["peers"] = {"input": {key: market.get(key) for key in PEER_KEYS}, "krx": peers, "excluded": excluded}
        if peers is None:
            # 입력 중간값으로 excess_pct 를 내면 종목은 KRX, 대형주는 입력 시세라 두 출처가 섞인다. 비교를 null 로 둔다.
            # 키는 지우지 않는다 — 프롬프트 1부 스키마가 "없으면 null" 이라 모델이 늘 같은 칸을 본다
            new_market.update(dict.fromkeys((*PEER_KEYS, "excess_pct")))
            excess = None
        else:
            new_market.update(peers)
            excess = round(krx - peers["peer_median_pct"], RATE_DECIMALS)
            new_market["excess_pct"] = excess
        record["excess_pct"] = {"input": market.get("excess_pct"), "recomputed": excess}
    out["market"] = new_market
    return out, record


def _is_rate(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# 입력 market 의 대형주 비교 수치. universe_peers 가 이 이름으로 돌려준다.
PEER_KEYS = ("peer_median_pct", "peer_up", "peer_down", "peer_total")


def universe_peers(
    stocks: list[StockDaily], code: str, universe: Iterable[str],
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """(대형주 비교 수치, 뺀 종목). 유니버스에서 대상 종목 자신을 빼고 KRX 등락률로 중간값·상승·하락·전체 수를 낸다.

    응답에 없는(missing)·거래정지(no_trades)·등락률 빈 칸(no_rate) 종목은 빼고 이유를 남긴다. 보합(0.00)은 전체 수에만
    든다. 쓸 종목이 없으면 (None, 뺀 종목).
    """
    by_code = {s.code: s for s in stocks}
    rates: list[float] = []
    excluded: list[dict[str, str]] = []
    for member in universe:
        if member == code:
            continue
        stock = by_code.get(member)
        reason = ("missing" if stock is None else "no_trades" if stock.no_trades
                  else "no_rate" if stock.change_rate is None else None)
        if reason:
            excluded.append({"code": member, "reason": reason})
        else:
            rates.append(stock.change_rate)
    if not rates:
        return None, excluded
    return {
        "peer_median_pct": round(statistics.median(rates), RATE_DECIMALS),
        "peer_up": sum(r > 0 for r in rates),
        "peer_down": sum(r < 0 for r in rates),
        "peer_total": len(rates),
    }, excluded


def to_input(ctx: MarketContext, groups: Mapping[str, Mapping[str, str]] = GROUPS) -> dict[str, Any]:
    """MarketContext → 프롬프트 1부 market_compare 형식."""
    return {
        "status": ctx.status,
        "status_reason": ctx.status_reason,
        "kospi": {key: getattr(ctx.kospi, key) for key in KOSPI_KEYS} if ctx.kospi else None,
        "peers": [{
            "group": p.group,
            "median_change_rate_pct": p.median_change_rate_pct,
            "excess_vs_group_pp": p.excess_vs_group_pp,
            "peer_count": p.peer_count,
            "relation": p.relation,
            "members_used": [{"code": c, "name": groups[p.group][c]} for c in p.members_used],
            "members_excluded": [e.model_dump() for e in p.members_excluded],
        } for p in ctx.peers],
    }
