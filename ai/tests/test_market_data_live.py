"""KRX·ECOS 를 실제로 호출한다. fixture 가 실제 응답 모양과 어긋나지 않았는지 본다.

**기본 실행에서 빠진다.** network 마커가 붙어 있고, 키가 없으면 그 API 테스트는 건너뛴다.

    uv run pytest -m network -s tests/test_market_data_live.py

KRX 는 키와 별개로 kospi_dd_trd·stk_bydd_trd 이용신청이 승인돼 있어야 한다.
"""

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import settings
from app.services.market_data import (
    GROUPS,
    IndexDaily,
    build_market_context,
    compute_excess,
    fetch_base_rate,
    fetch_kospi,
    fetch_stock,
    fetch_stock_daily,
    fetch_usd_krw,
)

pytestmark = pytest.mark.network

# 당일은 데이터가 없다(T+1). 연휴가 길어도 이만큼 거슬러 가면 영업일이 하나는 있다.
LOOKBACK_DAYS = 10
SAMSUNG = "005930"
KB = "105560"
# 보통주로 재계산한 코스피 등락률과 실제 코스피의 허용 차이(%p). 2026-10-27 은 0.005%p 였다.
# 넘으면 보통주 판별 규칙(코드 끝자리 0, 외국주 9로 시작)이나 전일 시총 역산이 틀어진 것이다.
RECOMPUTE_TOLERANCE_PP = 0.01
KST = timezone(timedelta(hours=9))


def _today() -> date:
    return datetime.now(KST).date()


def _need(name: str) -> None:
    if not (getattr(settings, name) or "").strip():
        pytest.skip(f"{name.upper()} 없음 — ai/.env 에 넣으면 돈다")


async def _latest_kospi(client: httpx.AsyncClient) -> tuple[date, IndexDaily]:
    """오늘 이전의 가장 최근 영업일과 그날 코스피."""
    today = _today()
    for back in range(1, LOOKBACK_DAYS + 1):
        day = today - timedelta(days=back)
        kospi = await fetch_kospi(client, day)
        if kospi is not None:
            return day, kospi
    pytest.fail(f"최근 {LOOKBACK_DAYS}일 동안 코스피 데이터가 없다")


async def test_krx_latest_business_day() -> None:
    _need("krx_auth_key")
    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        today = _today()
        # 당일 데이터가 몇 시부터 들어오는지는 아직 모른다(조사 문서 10절). 단정하지 않고 찍기만 한다.
        on_today = await fetch_kospi(client, today)
        print(f"\n당일({today}) 코스피: {'있음' if on_today else '없음'}")
        day, kospi = await _latest_kospi(client)
        stock = await fetch_stock(client, day, SAMSUNG)

    print(f"{day} 코스피 {kospi.close} ({kospi.change_rate}%)")
    assert kospi.close and kospi.close > 0
    assert kospi.change_rate is not None
    assert stock is not None, f"{day} 에 {SAMSUNG} 이 없다"
    move = compute_excess(stock, kospi)
    assert move is not None, f"{day} 에 {SAMSUNG} 체결이 없다(거래정지?)"
    print(f"{stock.name} {stock.close}원 ({stock.change_rate}%) → 초과분 {move.excess_rate}%p")


async def test_market_context_latest_business_day() -> None:
    """보통주 재계산 등락률이 실제 코스피와 맞는지, 그룹 코드가 응답에 다 있는지 본다."""
    _need("krx_auth_key")
    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        day, kospi = await _latest_kospi(client)
        stocks = await fetch_stock_daily(client, day)

    listed = {s.code for s in stocks}
    missing = sorted({c for members in GROUPS.values() for c in members} - listed)
    print(f"\n{day} 그룹 코드 중 응답에 없는 것: {missing or '없음'}")

    for code in (SAMSUNG, KB):
        ctx = build_market_context(code, day, kospi, stocks)
        assert ctx.status in ("ok", "no_trades"), ctx.status_reason
        k = ctx.kospi
        print(f"{ctx.name} {k.stock_change_rate_pct}% | 비중 {k.kospi_weight_pct}%"
              f" 기여도 {k.kospi_contribution_pp}%p | 자기 제외 코스피 {k.kospi_ex_self_change_rate_pct}%"
              f" 초과분 {k.excess_vs_kospi_ex_self_pp}%p | {k.kospi_basis} 기준 {k.kospi_relation}")
        # 실제 분모로 본 비중: 삼성전자 28%대, KB금융 1%대
        assert k.kospi_basis == ("kospi_ex_self" if code == SAMSUNG else "kospi")
        for peer in ctx.peers:
            print(f"  {peer.group}: 중앙값 {peer.median_change_rate_pct}% 초과분 {peer.excess_vs_group_pp}%p"
                  f" (쓴 종목 {peer.members_used})")

    print(f"재계산 코스피 {k.kospi_recomputed_change_rate_pct}% / 실제 {kospi.change_rate}%"
          f" (보통주 전일 시총 합 {k.common_prev_market_cap_krw:,}원)")
    gap = abs(k.kospi_recomputed_change_rate_pct - kospi.change_rate)
    assert gap <= RECOMPUTE_TOLERANCE_PP, (
        f"재계산 등락률이 실제와 {gap:.3f}%p 다르다. 보통주 판별 규칙이나 전일 시총 역산을 확인한다")


async def test_ecos_usd_krw_and_base_rate() -> None:
    _need("ecos_api_key")
    today = _today()
    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        usd = await fetch_usd_krw(client, today - timedelta(days=30), today)
        rate = await fetch_base_rate(client, today - timedelta(days=365), today)

    print(f"\n원/달러 {usd[-1].time} {usd[-1].value}{usd[-1].unit}" if usd else "\n원/달러 없음")
    print(f"기준금리 {rate[-1].time} {rate[-1].value}{rate[-1].unit}" if rate else "기준금리 없음")
    assert usd, "최근 30일 환율이 비었다"
    assert all(p.value and 500 < p.value < 3000 for p in usd)
    assert rate, "최근 1년 기준금리가 비었다"
    assert all(p.value is not None and 0 <= p.value < 20 for p in rate)
