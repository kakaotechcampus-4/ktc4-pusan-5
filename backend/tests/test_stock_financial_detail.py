from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.collectors.stocks import StockWorker
from app.main import app
from app.models.stock import StockCollectionJob, StockCollectionState
from app.models.stock_financials import StockAnnualEps, StockAnnualIncome
from app.repositories import stock_financials
from app.services import stock_financial_detail
from app.services.market_data import MarketDataError
from app.services.stock_financials import AnnualIncome

pytest_plugins = ("tests.test_stock_detail",)


@respx.mock
async def test_cold_financial_request_enqueues_each_resource_once(stock_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            response = await client.get("/api/stocks/TST001/financials")
            assert response.status_code == 200
            body = response.json()
            assert body["income"]["status"] == "pending"
            assert body["eps"]["status"] == "pending"
            assert body["income"]["data"] is None
            assert body["eps"]["data"] is None

    async with stock_db() as session:
        jobs = (
            await session.scalars(
                select(StockCollectionJob).where(StockCollectionJob.stock_code == "TST001")
            )
        ).all()
        assert len([job for job in jobs if job.resource == "income"]) == 1
        assert len([job for job in jobs if job.resource == "eps"]) == 1
    assert not respx.calls


async def test_financial_values_preserve_null_zero_negative_and_states_are_independent(stock_db):
    now = datetime.now(UTC)
    async with stock_db() as session:
        await stock_financials.save_periods(
            session,
            "TST001",
            "income",
            [
                {
                    "period_end": date(2025, 3, 31),
                    "revenue": Decimal(0),
                    "operating_profit": Decimal(-2),
                    "net_income": None,
                }
            ],
            now,
        )
        await stock_financials.save_periods(
            session,
            "TST001",
            "eps",
            [{"period_end": date(2025, 3, 31), "eps": Decimal(0)}],
            now,
        )
        await StockWorker._state(session, "TST001", "income", "INCOME_FAILED", False, now)
        await StockWorker._state(session, "TST001", "eps", None, True, now)
        await session.commit()

    async with stock_db() as session:
        response = await stock_financial_detail.financials(session, "TST001")
        assert response.income.status == "stale"
        assert response.eps.status == "ready"
        assert response.income.data[0].revenue == 0
        assert response.income.data[0].operating_profit == -2
        assert response.income.data[0].net_income is None
        assert response.eps.data[0].eps == 0


async def test_empty_success_is_cached_for_24_hours(stock_db):
    now = datetime.now(UTC)
    async with stock_db() as session:
        for resource in ("income", "eps"):
            assert await stock_financials.save_periods(session, "TST001", resource, [], now) is None
            await StockWorker._state(session, "TST001", resource, None, True, now)
        await session.commit()

    async with stock_db() as session:
        response = await stock_financial_detail.financials(session, "TST001")
        assert response.income.status == "empty"
        assert response.eps.status == "empty"
        assert response.income.data == []
        assert response.eps.data == []
        jobs = (
            await session.scalars(
                select(StockCollectionJob).where(StockCollectionJob.stock_code == "TST001")
            )
        ).all()
        assert not [job for job in jobs if job.resource in {"income", "eps"}]


async def test_older_financial_response_is_rejected_same_period_is_replaced(stock_db):
    now = datetime.now(UTC)
    async with stock_db() as session:
        assert (
            await stock_financials.save_periods(
                session,
                "TST001",
                "income",
                [
                    {
                        "period_end": date(2025, 3, 31),
                        "revenue": Decimal(100),
                        "operating_profit": Decimal(10),
                        "net_income": Decimal(5),
                    },
                    {
                        "period_end": date(2026, 3, 31),
                        "revenue": Decimal(200),
                        "operating_profit": Decimal(20),
                        "net_income": Decimal(10),
                    },
                ],
                now,
            )
            is None
        )
        result = await stock_financials.save_periods(
            session,
            "TST001",
            "income",
            [
                {
                    "period_end": date(2025, 3, 31),
                    "revenue": Decimal(1),
                    "operating_profit": None,
                    "net_income": None,
                }
            ],
            now + timedelta(seconds=1),
        )
        assert result == "OUTDATED_RESPONSE"
        assert await session.scalar(
            select(StockAnnualIncome.revenue).where(
                StockAnnualIncome.stock_code == "TST001",
                StockAnnualIncome.period_end == date(2026, 3, 31),
            )
        ) == Decimal(200)

        assert (
            await stock_financials.save_periods(
                session,
                "TST001",
                "income",
                [
                    {
                        "period_end": date(2026, 3, 31),
                        "revenue": Decimal(250),
                        "operating_profit": None,
                        "net_income": None,
                    }
                ],
                now + timedelta(seconds=2),
            )
            is None
        )
        assert await session.scalar(
            select(StockAnnualIncome.revenue).where(
                StockAnnualIncome.stock_code == "TST001",
                StockAnnualIncome.period_end == date(2026, 3, 31),
            )
        ) == Decimal(250)


async def test_worker_saves_income_and_failed_eps_keeps_previous_rows(stock_db, monkeypatch):
    from app.collectors import stocks
    from app.repositories import stock as stock_repo

    now = datetime.now(UTC)
    async with stock_db() as session:
        await stock_repo.enqueue(session, "TST001", "income", now, priority=-1000)
        await stock_repo.enqueue(session, "TST001", "eps", now, priority=-999)
        await stock_financials.save_periods(
            session,
            "TST001",
            "eps",
            [{"period_end": date(2025, 3, 31), "eps": Decimal("1.5")}],
            now,
        )
        await StockWorker._state(session, "TST001", "eps", None, True, now)
        await session.commit()

    class FakeKis:
        pass

    async def _noop():
        return None

    async def fetch_income(_kis, _code):
        return [AnnualIncome(date(2026, 3, 31), Decimal(100), Decimal(-2), None)]

    async def fetch_eps(_kis, _code):
        raise MarketDataError("UPSTREAM_FAILURE")

    monkeypatch.setattr(stocks.StockWorker, "schedule_active", lambda self: _noop())
    monkeypatch.setattr(stocks.stock_financials, "fetch_income", fetch_income)
    monkeypatch.setattr(stocks.stock_financials, "fetch_eps", fetch_eps)
    monkeypatch.setattr(stocks, "SessionLocal", stock_db)

    worker = stocks.StockWorker(None, FakeKis())
    assert await worker.tick() is True
    assert await worker.tick() is True

    async with stock_db() as session:
        income = (
            await session.scalars(
                select(StockAnnualIncome).where(StockAnnualIncome.stock_code == "TST001")
            )
        ).all()
        eps = (
            await session.scalars(
                select(StockAnnualEps).where(StockAnnualEps.stock_code == "TST001")
            )
        ).all()
        eps_state = await session.get(StockCollectionState, ("TST001", "eps"))
        assert len(income) == 1
        assert income[0].revenue == Decimal(100)
        assert income[0].operating_profit == Decimal(-2)
        assert len(eps) == 1
        assert eps[0].eps == Decimal("1.5")
        assert eps_state.error_code == "UPSTREAM_FAILURE"
