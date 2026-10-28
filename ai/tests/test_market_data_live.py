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
    compute_excess,
    fetch_base_rate,
    fetch_kospi,
    fetch_stock,
    fetch_usd_krw,
)

pytestmark = pytest.mark.network

# 당일은 데이터가 없다(T+1). 연휴가 길어도 이만큼 거슬러 가면 영업일이 하나는 있다.
LOOKBACK_DAYS = 10
SAMSUNG = "005930"
KST = timezone(timedelta(hours=9))


def _today() -> date:
    return datetime.now(KST).date()


def _need(name: str) -> None:
    if not (getattr(settings, name) or "").strip():
        pytest.skip(f"{name.upper()} 없음 — ai/.env 에 넣으면 돈다")


async def test_krx_latest_business_day() -> None:
    _need("krx_auth_key")
    async with httpx.AsyncClient(timeout=settings.http_timeout_sec) as client:
        today = _today()
        # 당일 데이터가 몇 시부터 들어오는지는 아직 모른다(조사 문서 10절). 단정하지 않고 찍기만 한다.
        on_today = await fetch_kospi(client, today)
        print(f"\n당일({today}) 코스피: {'있음' if on_today else '없음'}")

        for back in range(1, LOOKBACK_DAYS + 1):
            day = today - timedelta(days=back)
            kospi = await fetch_kospi(client, day)
            if kospi is not None:
                break
        else:
            pytest.fail(f"최근 {LOOKBACK_DAYS}일 동안 코스피 데이터가 없다")

        stock = await fetch_stock(client, day, SAMSUNG)

    print(f"{day} 코스피 {kospi.close} ({kospi.change_rate}%)")
    assert kospi.close and kospi.close > 0
    assert kospi.change_rate is not None
    assert stock is not None, f"{day} 에 {SAMSUNG} 이 없다"
    move = compute_excess(stock, kospi)
    assert move is not None, f"{day} 에 {SAMSUNG} 체결이 없다(거래정지?)"
    print(f"{stock.name} {stock.close}원 ({stock.change_rate}%) → 초과분 {move.excess_rate}%p")


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
