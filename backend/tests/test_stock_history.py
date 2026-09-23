from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select

from app.models.stock import StockCollectionJob
from app.repositories import stock_history as repo
from app.schemas.stock import Resource
from app.schemas.stock_investment import Growth, InvestmentPoint
from app.services import krx_history
from app.services.stock_history_detail import enrich_history
from tests import test_stock_detail

stock_db = test_stock_detail.stock_db


def investment():
    return Resource(
        status="ready",
        data=[
            InvestmentPoint(
                fiscal_period="2025-12",
                revenue_growth=Growth(),
                operating_profit_growth=Growth(),
                net_income_growth=Growth(),
            )
        ],
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
