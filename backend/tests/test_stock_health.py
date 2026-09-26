from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.collectors.stocks import StockWorker
from app.models.stock import StockCollectionJob
from app.repositories.stock_financials import save_periods
from app.schemas.stock import Resource
from app.schemas.stock_financials import AnnualEps, AnnualIncome, AnnualStability
from app.services.stock_financial_detail import financials, health_summary
from tests import test_stock_detail

stock_db = test_stock_detail.stock_db


def section(data, status="ready", **kwargs):
    return Resource(data=data, status=status, refreshing=False, **kwargs)


def test_health_exact_period_and_percent_units():
    result = health_summary(
        {
            "income": section(
                [AnnualIncome(fiscal_period="2026-06", revenue=100, operating_profit=-2)]
            ),
            "eps": section(
                [AnnualEps(fiscal_period="2026-06", eps=0, roe=-8.02, debt_ratio=157.14)]
            ),
            "stability": section([AnnualStability(fiscal_period="2026-06", current_ratio=121.92)]),
        }
    )
    assert result.status == "ready"
    assert result.data.operating_margin == -2
    assert result.data.roe == -8.02
    assert result.data.debt_ratio == 157.14
    assert result.data.current_ratio == 121.92


def test_health_never_mixes_different_periods_and_handles_zero_revenue():
    result = health_summary(
        {
            "income": section(
                [AnnualIncome(fiscal_period="2026-06", revenue=0, operating_profit=10)]
            ),
            "eps": section([AnnualEps(fiscal_period="2025-12", roe=10, debt_ratio=50)]),
            "stability": section([AnnualStability(fiscal_period="2026-06", current_ratio=0)]),
        }
    )
    assert result.status == "stale"
    assert result.data.fiscal_period == "2026-06"
    assert result.data.roe is None
    assert result.data.operating_margin is None
    assert result.data.current_ratio == 0


def test_health_uses_latest_common_period_and_keeps_partial_failure():
    result = health_summary(
        {
            "income": section(
                [
                    AnnualIncome(fiscal_period="2026-06", revenue=100, operating_profit=20),
                    AnnualIncome(fiscal_period="2025-12", revenue=100, operating_profit=10),
                ]
            ),
            "eps": section([AnnualEps(fiscal_period="2025-12", roe=7)]),
            "stability": section(None, "unavailable", retry_after_seconds=30),
        }
    )
    assert result.status == "stale"
    assert result.data.fiscal_period == "2025-12"
    assert result.data.operating_margin == 10
    assert result.data.roe == 7
    assert result.data.current_ratio is None
    assert result.retry_after_seconds == 30


async def test_health_persists_and_reuses_financial_jobs(stock_db):
    now = datetime.now(UTC)
    async with stock_db() as session:
        cold = await financials(session, "TST001")
        assert cold.health.status == "pending"
        await financials(session, "TST001")
        jobs = (
            await session.scalars(
                select(StockCollectionJob).where(StockCollectionJob.stock_code == "TST001")
            )
        ).all()
        assert sorted(job.resource for job in jobs) == [
            "eps",
            "income",
            "quarter_income",
            "quarter_ratios",
            "stability",
        ]
        for kind, row in (
            (
                "income",
                {"revenue": Decimal(100), "operating_profit": Decimal(20), "net_income": None},
            ),
            ("eps", {"eps": Decimal(1), "roe": Decimal(12), "debt_ratio": Decimal(30)}),
            ("stability", {"current_ratio": Decimal(200)}),
        ):
            await save_periods(
                session, "TST001", kind, [{"period_end": date(2025, 12, 31), **row}], now
            )
            await StockWorker._state(session, "TST001", kind, None, True, now)
        for job in jobs:
            job.status = "idle"
        await session.commit()
    async with stock_db() as session:
        ready = await financials(session, "TST001")
        assert ready.health.status == "ready"
        assert ready.health.data.current_ratio == 200
        assert ready.health.data.operating_margin == 20
        assert not ready.health.refreshing
        assert ready.health.retry_after_seconds is None
