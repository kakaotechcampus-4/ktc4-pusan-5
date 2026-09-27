from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.collectors.stocks import StockWorker
from app.models.stock import StockCollectionJob
from app.repositories.stock_financials import save_periods
from app.schemas.stock import Resource
from app.schemas.stock_financials import AnnualEps, AnnualIncome
from app.schemas.stock_investment import QuarterlyIncome
from app.services.stock_financial_detail import financials
from app.services.stock_investment import growth, investment_summary, single_quarter
from tests import test_stock_detail

stock_db = test_stock_detail.stock_db


def income(period, revenue, profit, net=None, month=12):
    return QuarterlyIncome(
        fiscal_period=period,
        revenue=revenue,
        operating_profit=profit,
        net_income=net,
        fiscal_year_end_month=month,
    )


def resource(rows, status="ready"):
    return Resource(status=status, data=rows)


def test_cumulative_to_single_quarter_and_yoy():
    result = investment_summary(
        resource(
            [
                income("2024-06", 100, 10, 4),
                income("2024-09", 150, 20, 8),
                income("2025-06", 200, 20, 10),
                income("2025-09", 300, 50, 22),
            ]
        ),
        resource([AnnualEps(fiscal_period="2025-09", eps=20, roe=12, debt_ratio=30)]),
        resource([AnnualIncome(fiscal_period="2023-12"), AnnualIncome(fiscal_period="2024-12")]),
    )
    latest = result.data[-1]
    assert latest.operating_profit == 30
    assert latest.net_income == 12
    assert latest.revenue_growth.value == 100
    assert latest.operating_profit_growth.value == 200
    assert latest.net_income_growth.value == 200
    assert latest.eps_cumulative == 20
    assert latest.rs is latest.per is latest.pbr is latest.market_cap is None


def test_fiscal_year_end_and_missing_predecessor_are_not_guessed():
    rows = {
        r.fiscal_period: r
        for r in [income("2025-06", 100, 10, month=3), income("2025-09", 150, 30, month=3)]
    }
    assert single_quarter(rows, "2025-06", "operating_profit", {"2025-03"}) == 10
    assert single_quarter(rows, "2025-09", "operating_profit", {"2025-03"}) == 20
    assert single_quarter(rows, "2025-09", "operating_profit", {"2024-12"}) is None
    rows.pop("2025-06")
    assert single_quarter(rows, "2025-09", "operating_profit", {"2025-03"}) is None
    rows["2025-09"].fiscal_year_end_month = None
    assert single_quarter(rows, "2025-09", "operating_profit", {"2025-03"}) is None


@pytest.mark.parametrize(
    "current,previous,status,value",
    [
        (20, 10, "value", 100),
        (0, 10, "value", -100),
        (10, -10, "turned_profit", None),
        (-10, 10, "turned_loss", None),
        (-5, -10, "loss_narrowed", None),
        (-20, -10, "loss_widened", None),
        (-10, -10, "loss_unchanged", None),
        (10, 0, "zero_base", None),
        (None, 10, "unavailable", None),
    ],
)
def test_growth_states(current, previous, status, value):
    result = growth(current, previous)
    assert result.status == status
    assert result.value == value


def test_partial_failure_retains_ratios_and_never_subtracts_eps():
    result = investment_summary(
        resource(None, "unavailable"),
        resource([AnnualEps(fiscal_period="2025-09", eps=-4)]),
        resource([], "empty"),
    )
    assert result.status == "stale"
    assert result.data[0].eps_cumulative == -4
    assert result.data[0].operating_profit is None


async def test_quarterly_jobs_deduplicate_and_stored_contract_is_reused(stock_db):
    now = datetime.now(UTC)
    async with stock_db() as session:
        for _ in range(2):
            result = await financials(session, "TST001")
            assert result.investment.status == "pending"
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
        for kind, rows in (
            (
                "income",
                [
                    {
                        "period_end": date(2024, 12, 31),
                        "revenue": Decimal(100),
                        "operating_profit": Decimal(10),
                        "net_income": None,
                    }
                ],
            ),
            (
                "quarter_income",
                [
                    {
                        "period_end": date(2025, 3, 31),
                        "revenue": Decimal(50),
                        "operating_profit": Decimal(7),
                        "net_income": None,
                        "fiscal_year_end_month": 12,
                    }
                ],
            ),
            (
                "quarter_ratios",
                [
                    {
                        "period_end": date(2025, 3, 31),
                        "eps": Decimal(3),
                        "roe": Decimal(5),
                        "debt_ratio": None,
                    }
                ],
            ),
        ):
            await save_periods(session, "TST001", kind, rows, now)
            await StockWorker._state(session, "TST001", kind, None, True, now)
        for job in jobs:
            job.status = "idle"
        await session.commit()
    async with stock_db() as session:
        result = await financials(session, "TST001")
        assert result.investment.status == "ready"
        assert result.investment.refreshing  # 과거 시총/RS는 별도 lazy 작업이다.
        assert result.investment.data[-1].operating_profit == 7
        assert result.investment.data[-1].eps_cumulative == 3
