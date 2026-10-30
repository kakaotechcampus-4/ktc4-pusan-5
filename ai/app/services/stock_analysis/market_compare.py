"""입력 market_compare 칸. 시장 맥락(market_data.context)을 프롬프트 1부 입력 형식으로 옮긴다.

    compare_for = MarketCompare(client)          # 실행 하나에 하나
    compare, error = await compare_for(payload)

러너가 보고서마다 입력에 넣는다(collectors.stock_analysis). 입력에 같은 칸이 있어도 다시 계산해 덮어쓴다 —
market 계산 칸과 같이 계산은 한 곳에서만 한다.

## KRX 는 기준일마다 한 번

fetch_market_context 는 부를 때마다 KRX 를 두 번 부른다(코스피 지수, 유가증권 전 종목 900여 건). 같은 날
보고서가 여럿이면 같은 응답을 종목 수만큼 받게 된다. 그래서 그 함수를 쓰지 않고, 기준일마다 두 응답을 한 번
받아 두고 종목마다 build_market_context 만 부른다. 같은 날 보고서가 동시에 들어와도 기준일마다 Task 하나를
함께 기다리므로 호출은 한 번이다. **실패도 기준일마다 한 번만 시도한다** — 그 날 보고서는 모두 같은 사유로
비교 없이 만든다. 같은 실행 안에서 다시 시도하지 않는다.

## KRX 를 못 읽어도 보고서는 만든다

호출·계산이 실패하면 칸을 null 로 두고 사유를 돌려준다(래퍼 market_compare_error). 기준일 데이터가 없으면
status 가 no_data 인 칸이 그대로 간다. 어느 쪽이든 프롬프트 3단계 「비교 수치」가 코스피·그룹 비교 문장을 쓰지
않게 한다. 나머지 보고서는 그대로 만든다.

프롬프트 1부에 적힌 칸만 보낸다. 비중의 분모·재계산 코스피·weight_basis 는 검수용이라 모델에 보내지 않는다.
members_used 는 코드만 있어서 그룹 정의(peer_groups)에서 이름을 붙인다.
"""

import asyncio
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

import httpx

from app.services.market_data import (
    GROUPS,
    IndexDaily,
    MarketContext,
    StockDaily,
    build_market_context,
    fetch_kospi,
    fetch_stock_daily,
)

logger = logging.getLogger(__name__)

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


class MarketCompare:
    """실행 하나의 market_compare 칸을 만든다. 기준일별 KRX 응답을 실행이 끝날 때까지 들고 있는다."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._days: dict[date, asyncio.Task[Day]] = {}

    async def __call__(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """(입력 칸, 실패 사유). 실패하면 (None, 사유), 아니면 (칸, None). 예외를 올리지 않는다."""
        code, target_date = payload["code"], payload["target_date"]
        day = date.fromisoformat(target_date)
        if day not in self._days:
            self._days[day] = asyncio.create_task(self._fetch(day))
        try:
            kospi, stocks = await self._days[day]
            ctx = build_market_context(str(code), day, kospi, stocks)
        # MarketDataError(KRX 호출 실패·응답 깨짐)와 키 없음은 RuntimeError, 등락률 빈 칸·보통주 0개는 ValueError 다
        except (RuntimeError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("시장 맥락을 못 읽어 비교 없이 만든다 (%s %s): %s", code, target_date, error)
            return None, error
        return to_input(ctx), None

    async def _fetch(self, day: date) -> Day:
        """fetch_market_context 와 같은 두 호출. 코스피가 없는 날은 전 종목을 부르지 않는다."""
        kospi = await fetch_kospi(self._client, day)
        stocks = await fetch_stock_daily(self._client, day) if kospi is not None else []
        return kospi, stocks


def to_input(ctx: MarketContext, groups: Mapping[str, Mapping[str, str]] = GROUPS) -> dict[str, Any]:
    """MarketContext → 프롬프트 1부 market_compare 형식."""
    return {
        "status": ctx.status,
        "status_reason": ctx.status_reason,
        "kospi": {key: getattr(ctx.kospi, key) for key in KOSPI_KEYS} if ctx.kospi else None,
        "peers": [{
            "group": p.group,
            "avg_change_rate_pct": p.avg_change_rate_pct,
            "excess_vs_group_pp": p.excess_vs_group_pp,
            "peer_count": p.peer_count,
            "relation": p.relation,
            "members_used": [{"code": c, "name": groups[p.group][c]} for c in p.members_used],
            "members_excluded": [e.model_dump() for e in p.members_excluded],
        } for p in ctx.peers],
    }
