from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select

from app.models.stock import StockCollectionJob, StockDailyPrice
from app.repositories import stock_history as repo
from app.schemas.stock import Resource
from app.schemas.stock_investment import Growth, InvestmentPoint
from app.services import krx_history
from app.services.stock_history_detail import enrich_history
from tests import test_stock_detail

stock_db = test_stock_detail.stock_db


def investment(net_income_ttm=None, bps=None):
    return Resource(
        status="ready",
        data=[
            InvestmentPoint(
                fiscal_period="2025-12",
                revenue_growth=Growth(),
                operating_profit_growth=Growth(),
                net_income_growth=Growth(),
                net_income_ttm=net_income_ttm,
                bps=bps,
            )
        ],
    )


PERIOD_END = date(2025, 12, 31)
CAP_AS_OF = date(2025, 12, 30)


async def save_cap(session, market_cap=1000, cap_as_of=CAP_AS_OF):
    await repo.save_history(
        session,
        "TST001",
        PERIOD_END,
        "history_cap",
        {"market_cap": market_cap, "cap_as_of": cap_as_of},
        datetime.now(UTC),
    )


def save_close(session, close, trade_date=CAP_AS_OF):
    session.add(
        StockDailyPrice(
            stock_code="TST001",
            trade_date=trade_date,
            adjustment_type="raw",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1,
            collected_at=datetime.now(UTC),
        )
    )


async def test_history_jobs_deduplicate_and_empty_success_is_cached(stock_db):
    async with stock_db() as s:
        for _ in range(2):
            result = await enrich_history(s, "TST001", investment())
            assert result.refreshing
        jobs = (
            await s.scalars(
                select(StockCollectionJob).where(StockCollectionJob.stock_code == "TST001")
            )
        ).all()
        assert sorted(j.resource for j in jobs) == ["history_cap", "history_rs"]
        await repo.save_history(
            s,
            "TST001",
            date(2025, 12, 31),
            "history_cap",
            {"market_cap": 100, "cap_as_of": date(2025, 12, 30)},
            datetime.now(UTC),
        )
        await repo.save_history(
            s, "TST001", date(2025, 12, 31), "history_rs", None, datetime.now(UTC)
        )
        for j in jobs:
            j.status = "idle"
        await s.commit()
    async with stock_db() as s:
        result = await enrich_history(s, "TST001", investment())
        assert not result.refreshing
        assert result.data[0].market_cap == 100
        assert result.data[0].rs is None
        assert result.retry_after_seconds is None


async def test_krx_market_day_response_is_reused(stock_db, monkeypatch):
    monkeypatch.setattr(krx_history, "SessionLocal", stock_db)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(
            200, json={"OutBlock_1": [{"BAS_DD": "20000104", "ISU_CD": "TST001", "MKTCAP": "100"}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await krx_history.krx_rows(client, "KOSPI", "stock", date(2000, 1, 4))
        second = await krx_history.krx_rows(client, "KOSPI", "stock", date(2000, 1, 4))
        assert first == second
        assert len(calls) == 1


async def test_per_and_pbr_are_filled_when_cap_and_close_exist(stock_db):
    async with stock_db() as s:
        await save_cap(s, market_cap=1000)
        save_close(s, close=50)
        await s.commit()
        result = await enrich_history(s, "TST001", investment(net_income_ttm=100, bps=25))
        point = result.data[0]
        assert point.per == 10
        assert point.pbr == 2


async def test_per_and_pbr_are_none_without_saved_row(stock_db):
    async with stock_db() as s:
        result = await enrich_history(s, "TST001", investment(net_income_ttm=100, bps=25))
        point = result.data[0]
        assert point.per is None
        assert point.pbr is None


async def test_pbr_is_none_but_per_stays_when_close_row_is_missing(stock_db):
    # 분기말 시가총액 기준일은 있지만 그날 종가가 stock_daily_price 에 없는 경우
    async with stock_db() as s:
        await save_cap(s, market_cap=1000)
        await s.commit()
        result = await enrich_history(s, "TST001", investment(net_income_ttm=100, bps=25))
        point = result.data[0]
        assert point.per == 10
        assert point.pbr is None


async def test_per_and_pbr_are_none_for_loss_and_capital_impairment(stock_db):
    async with stock_db() as s:
        await save_cap(s, market_cap=1000)
        save_close(s, close=50)
        await s.commit()
        result = await enrich_history(s, "TST001", investment(net_income_ttm=-100, bps=-5))
        point = result.data[0]
        assert point.per is None
        assert point.pbr is None
