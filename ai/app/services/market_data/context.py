"""종목 하나·기준일 하나의 시장 맥락. 보고서에 넣을 숫자를 전부 코드로 계산한다.

    ctx = await fetch_market_context(client, "005930", date(2026, 10, 27))
    ctx.kospi.excess_vs_kospi_pp          # 코스피 대비 초과분 (%p)
    ctx.kospi.kospi_contribution_pp       # 코스피 기여도 (%p)
    ctx.peers[0].excess_vs_group_pp       # 동종 그룹 대비 초과분 (%p)

KRX 를 두 번 부른다(코스피 지수, 유가증권 전 종목). 계산은 build_market_context 가 하고
네트워크를 쓰지 않는다. 여러 종목을 볼 때는 두 응답을 한 번 받아 build 를 여러 번 부른다.

## 코스피 비중 — 근사다

기여도에는 **장 시작 전(전일) 비중**이 맞다. 당일 시총에는 그날 오른 몫이 이미 들어 있다.
응답에 전일 시총이 없어서 `당일 시총 ÷ (1 + 등락률)` 로 역산한다. 그날 상장주식수가 바뀌었으면 틀린다.

분모는 KRX 지수 응답의 상장시가총액(MKTCAP)이 아니라 **보통주 전 종목의 전일 시총 합**이다.
2026-10-27 실제 응답으로 확인했다.

    지수 MKTCAP = 외국주 2종목을 뺀 전 종목 시총 합 (원 단위까지 같다) → 우선주가 들어 있다
    전일 시총 가중으로 지수 등락률을 다시 계산하면
        우선주 포함  3.120%
        보통주만     3.095%   ← 실제 코스피 3.09%
    삼성전자 비중이 MKTCAP 기준 27.88%, 보통주 기준 28.56% 로 1%p 가까이 다르다.

보통주는 종목코드 끝자리가 0 인 것으로 가린다(우선주는 5·7·9·K·L). 외국주는 코드가 9 로 시작한다.
이 규칙이 틀어지면 재계산 등락률이 실제와 벌어진다. 결과에 둘 다 남기고, live 테스트가 0.01%p
안에 드는지 본다.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from statistics import median
from typing import Literal

import httpx

from app.services.market_data.excess import compute_excess
from app.services.market_data.krx import fetch_kospi, fetch_stock_daily
from app.services.market_data.peer_groups import GROUPS, STOCK_GROUPS
from app.services.market_data.schema import (
    IndexDaily,
    KospiComparison,
    MarketContext,
    PeerComparison,
    PeerExclusion,
    StockDaily,
)

WEIGHT_BASIS = (
    "전일 시총 기준 근사. 종목·보통주 전일 시총은 당일 시총 ÷ (1 + 등락률) 로 역산했다"
    "(그날 상장주식수 변동은 반영하지 않음). 분모는 보통주(종목코드 끝자리 0, 외국주 제외) 전일 시총 합이다."
    " KRX 지수 응답의 상장시가총액은 우선주가 들어 있어 쓰지 않았다."
)
NO_DATA_REASON = "기준일 KRX 데이터가 없다(당일·휴장일이거나 아직 확정 전)"
NOT_FOUND_REASON = "그날 유가증권 일별매매정보에 없는 종목이다(코스닥 종목·상장폐지·코드 오류)"
NO_TRADES_REASON = (
    "거래정지(거래량 0). 등락률 0.00 은 보합이 아니라 거래가 없었던 것이라 초과분·기여도를 계산하지 않았다"
)
# 등락률·초과분·비중(%)은 KRX 등락률과 같은 소수 둘째 자리. 기여도는 0.003%p 처럼 작은 종목이
# 많아서 한 자리 더 둔다.
RATE_DECIMALS = 2
CONTRIBUTION_DECIMALS = 3
# 그룹 대비 초과분이 이 안(경계 포함)이면 그룹 흐름을 따라갔다고 본다 (%p). 방향이 반대면 opposite.
# 반올림한 excess_vs_group_pp 로 판정한다. 보고서에 보이는 숫자와 판정이 어긋나지 않게 하려는 것이다.
GROUP_FOLLOW_THRESHOLD_PP = 1.0
# 코스피 대비 초과분(kospi_basis 쪽)이 이 안(경계 포함)이면 시장 흐름을 따라갔다고 본다 (%p).
# 방향이 반대면 opposite. 그룹 판정처럼 반올림한 초과분으로 판정한다.
KOSPI_FOLLOW_THRESHOLD_PP = 1.0
# 코스피 비중이 이 이상(%)이면 자기 제외 코스피 대비 초과분으로 판정한다. 코스피 등락률에 자기 몫이
# 크게 섞여 있어서다. 같은 이유로 반올림한 kospi_weight_pct 로 가른다.
KOSPI_EX_SELF_WEIGHT_PCT = 10.0


async def fetch_market_context(client: httpx.AsyncClient, code: str, bas_dd: date) -> MarketContext:
    kospi = await fetch_kospi(client, bas_dd)
    stocks = await fetch_stock_daily(client, bas_dd) if kospi is not None else []
    return build_market_context(code, bas_dd, kospi, stocks)


def build_market_context(
    code: str,
    bas_dd: date,
    kospi: IndexDaily | None,
    stocks: list[StockDaily],
    *,
    groups: Mapping[str, Mapping[str, str]] = GROUPS,
    stock_groups: Mapping[str, tuple[str, ...]] = STOCK_GROUPS,
) -> MarketContext:
    """kospi 는 fetch_kospi, stocks 는 fetch_stock_daily 의 결과다(같은 기준일)."""
    if kospi is None or not stocks:
        return MarketContext(bas_dd=bas_dd, code=code, status="no_data", status_reason=NO_DATA_REASON)
    stock = next((s for s in stocks if s.code == code), None)
    if stock is None:
        return MarketContext(
            bas_dd=bas_dd, code=code, status="stock_not_found", status_reason=NOT_FOUND_REASON)

    return MarketContext(
        bas_dd=bas_dd,
        code=code,
        name=stock.name,
        status="no_trades" if stock.no_trades else "ok",
        status_reason=NO_TRADES_REASON if stock.no_trades else None,
        kospi=kospi_comparison(stock, kospi, stocks),
        peers=peer_comparisons(stock, stocks, stock_groups.get(code, ()), groups),
    )


def kospi_comparison(stock: StockDaily, kospi: IndexDaily, stocks: list[StockDaily]) -> KospiComparison:
    if stock.change_rate is None or kospi.change_rate is None:
        raise ValueError(f"{stock.bas_dd} {stock.code}·코스피 등락률 중 빈 칸이 있다")
    move = compute_excess(stock, kospi)  # 거래정지면 None
    base, recomputed = common_base(stocks)
    prev = prev_market_cap(stock)
    weight = prev / base if is_common(stock.code) and prev is not None else None

    contribution = ex_self = None
    if move is not None and weight is not None:
        contribution = stock.change_rate * weight  # %p
        ex_self = (kospi.change_rate - contribution) / (1 - weight)  # %

    excess_pp = move.excess_rate if move else None
    weight_pct = _round(weight * 100 if weight is not None else None, RATE_DECIMALS)
    ex_self_pct = _round(ex_self, RATE_DECIMALS)
    # 보이는 자기 제외 코스피 등락률(반올림 값)과 뺀다. 반올림 전 값과 빼면 1.0 경계에서 판정이 보이는 숫자와 어긋난다.
    excess_ex_self_pp = None if ex_self_pct is None else round(stock.change_rate - ex_self_pct, RATE_DECIMALS)
    basis = kospi_basis(weight_pct)
    if basis == "kospi_ex_self":
        relation = kospi_relation(excess_ex_self_pp, stock.change_rate, ex_self_pct)
    else:
        relation = kospi_relation(excess_pp, stock.change_rate, kospi.change_rate)
    return KospiComparison(
        stock_change_rate_pct=stock.change_rate,
        kospi_change_rate_pct=kospi.change_rate,
        excess_vs_kospi_pp=excess_pp,
        kospi_weight_pct=weight_pct,
        kospi_contribution_pp=_round(contribution, CONTRIBUTION_DECIMALS),
        kospi_ex_self_change_rate_pct=ex_self_pct,
        excess_vs_kospi_ex_self_pp=excess_ex_self_pp,
        kospi_basis=basis,
        kospi_relation=relation,
        common_prev_market_cap_krw=round(base),
        kospi_recomputed_change_rate_pct=round(recomputed, CONTRIBUTION_DECIMALS),
        weight_basis=WEIGHT_BASIS,
    )


def peer_comparisons(
    stock: StockDaily,
    stocks: list[StockDaily],
    group_names: Iterable[str],
    groups: Mapping[str, Mapping[str, str]] = GROUPS,
) -> list[PeerComparison]:
    """그룹마다 중앙값과 초과분. 자기 자신·거래정지·응답에 없는 종목은 중앙값에서 뺀다.

    평균이 아니라 중앙값이다. 한 종목만 튀어도(예: 9% 급등) 평균은 그쪽으로 끌려가 판정이 뒤집힌다.
    비교 종목이 둘 이하면 중앙값과 평균이 같다.
    """
    by_code = {s.code: s for s in stocks}
    result = []
    for group in group_names:
        used: list[str] = []
        excluded: list[PeerExclusion] = []
        rates: list[float] = []
        for code, name in groups[group].items():
            peer = by_code.get(code)
            if code == stock.code:
                reason = "self"
            elif peer is None:
                reason = "missing"
            elif peer.no_trades:
                reason = "no_trades"
            elif peer.change_rate is None:
                reason = "no_rate"
            else:
                used.append(code)
                rates.append(peer.change_rate)
                continue
            excluded.append(PeerExclusion(code=code, name=name, reason=reason))

        center = median(rates) if rates else None
        center_pct = _round(center, RATE_DECIMALS)
        excess = None
        # 보이는 중앙값(반올림 값)과 뺀다. 반올림 전 값과 빼면 1.0 경계에서 판정이 보이는 숫자와 어긋난다.
        if center_pct is not None and not stock.no_trades and stock.change_rate is not None:
            excess = round(stock.change_rate - center_pct, RATE_DECIMALS)
        result.append(PeerComparison(
            group=group,
            median_change_rate_pct=center_pct,
            excess_vs_group_pp=excess,
            peer_count=len(used),
            relation=group_relation(excess, len(used), stock.change_rate, center_pct,
                                    [_round(r, RATE_DECIMALS) for r in rates]),
            members_used=used,
            members_excluded=excluded,
        ))
    return result


def group_relation(
    excess_pp: float | None, peer_count: int, stock_rate: float | None, group_rate: float | None,
    member_rates: Sequence[float] = (),
) -> Literal["follows", "opposite", "diverges", "inconclusive"] | None:
    """그룹 비교 판정. 비교 종목이 하나뿐이면 차이가 그 종목 쪽 사정일 수 있어 단정하지 않는다.

    기준 안이어도 그룹과 오르내린 방향이 반대면 opposite 다. "같은 그룹과 함께 움직였다" 고 쓸 수 없다.

    member_rates 는 비교 종목(members_used)의 반올림한 등락률이다. 기준 안이고 방향도 반대가 아니어서 follows 일
    자리에서 비교 종목끼리 방향이 엇갈렸으면(is_mixed) inconclusive 로 둔다 — 그룹 중앙값 하나로 "그룹과 비슷하게"
    라고 쓰면 오른 종목과 내린 종목이 함께 오르거나 내린 것처럼 읽힌다. 다만 비교 종목이 셋 이상이고 한 방향이
    과반이면 follows 를 유지한다(mixed_still_follows). opposite·diverges 는 엇갈림과 상관없이 그대로다.
    """
    if excess_pp is None:
        return None
    if abs(excess_pp) <= GROUP_FOLLOW_THRESHOLD_PP:
        if is_opposite(stock_rate, group_rate):
            return "opposite"
        if is_mixed(member_rates) and not mixed_still_follows(stock_rate, member_rates):
            return "inconclusive"
        return "follows"
    return "diverges" if peer_count >= 2 else "inconclusive"


def is_mixed(member_rates: Sequence[float]) -> bool:
    """비교 종목들의 오르내린 방향이 엇갈렸나(오른 종목과 내린 종목이 함께 있다). 0.00(보합)은 방향이 없다.

    보고서에 보이는 숫자와 어긋나지 않게 반올림한 등락률을 받는다(is_opposite 와 같다).
    """
    return any(r > 0 for r in member_rates) and any(r < 0 for r in member_rates)


def mixed_still_follows(stock_rate: float | None, member_rates: Sequence[float]) -> bool:
    """방향이 엇갈린 그룹에서도 follows 를 유지하는가.

    비교 종목이 둘이면 유지하지 않는다(한쪽씩 갈렸다). 셋 이상이면 한 방향이 과반(비교 종목 수의 절반 초과)이고
    대상 종목도 그 방향이거나 보합(0.00, 방향 없음 — 반대 방향으로 치지 않는다)일 때 유지한다. 오른 수와 내린 수가
    같거나(반반) 과반이 없으면 유지하지 않는다.
    """
    n = len(member_rates)
    if n < 3 or stock_rate is None:
        return False
    up = sum(r > 0 for r in member_rates)
    down = sum(r < 0 for r in member_rates)
    if 2 * up > n:
        majority = 1
    elif 2 * down > n:
        majority = -1
    else:
        return False
    return stock_rate == 0 or (stock_rate > 0) == (majority > 0)


def kospi_basis(weight_pct: float | None) -> Literal["kospi", "kospi_ex_self"]:
    """코스피 판정에 쓸 초과분. 비중이 없으면(보통주가 아니면) 코스피와 그대로 비교한다."""
    if weight_pct is not None and weight_pct >= KOSPI_EX_SELF_WEIGHT_PCT:
        return "kospi_ex_self"
    return "kospi"


def kospi_relation(
    excess_pp: float | None, stock_rate: float | None, base_rate: float | None,
) -> Literal["follows", "opposite", "diverges"] | None:
    """코스피 비교 판정. 초과분이 없으면(거래정지) 판정하지 않는다.

    excess_pp·base_rate 는 kospi_basis 쪽 값이다(자기 제외면 자기 제외 코스피 등락률).
    기준 안이어도 오르내린 방향이 반대면 opposite 다. "코스피와 비슷하게 움직였다" 고 쓸 수 없다.
    """
    if excess_pp is None:
        return None
    if abs(excess_pp) > KOSPI_FOLLOW_THRESHOLD_PP:
        return "diverges"
    return "opposite" if is_opposite(stock_rate, base_rate) else "follows"


def is_opposite(stock_rate: float | None, base_rate: float | None) -> bool:
    """오르내린 방향이 반대인가. 0.00(보합)은 방향이 없어 어느 쪽과도 반대가 아니다.

    보고서에 보이는 숫자와 어긋나지 않게 반올림한 등락률을 받는다.
    """
    return stock_rate is not None and base_rate is not None and stock_rate * base_rate < 0


def is_common(code: str) -> bool:
    """보통주인가. 끝자리 0 이 보통주, 9 로 시작하면 외국주다(2026-10-27 응답의 900140·950210)."""
    return code.endswith("0") and not code.startswith("9")


def prev_market_cap(stock: StockDaily) -> float | None:
    """전일 시총(원) 역산. 당일 시총 ÷ (1 + 등락률). 상장주식수 변동은 반영하지 않는다."""
    if stock.market_cap is None or stock.change_rate is None:
        return None
    return stock.market_cap / (1 + stock.change_rate / 100)


def common_base(stocks: list[StockDaily]) -> tuple[float, float]:
    """(보통주 전일 시총 합 원, 그것으로 가중한 재계산 코스피 등락률 %)."""
    total = weighted = 0.0
    for stock in stocks:
        prev = prev_market_cap(stock) if is_common(stock.code) else None
        if prev is None:
            continue
        total += prev
        weighted += prev * stock.change_rate
    if total <= 0:
        raise ValueError("보통주 시총을 하나도 읽지 못했다. 보통주 판별 규칙이나 응답을 확인한다")
    return total, weighted / total


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)
