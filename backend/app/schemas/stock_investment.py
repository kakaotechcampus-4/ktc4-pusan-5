from datetime import date
from typing import Literal

from pydantic import FiniteFloat

from app.schemas.base import CamelModel


class QuarterlyIncome(CamelModel):
    fiscal_period: str
    revenue: FiniteFloat | None = None
    operating_profit: FiniteFloat | None = None
    net_income: FiniteFloat | None = None
    fiscal_year_end_month: int | None = None


class Growth(CamelModel):
    value: FiniteFloat | None = None
    status: Literal[
        "value",
        "turned_profit",
        "turned_loss",
        "loss_narrowed",
        "loss_widened",
        "loss_unchanged",
        "zero_base",
        "unavailable",
    ] = "unavailable"


class InvestmentPoint(CamelModel):
    fiscal_period: str
    revenue_growth: Growth
    operating_profit_growth: Growth
    net_income_growth: Growth
    operating_profit: FiniteFloat | None = None
    net_income: FiniteFloat | None = None
    eps_cumulative: FiniteFloat | None = None
    roe: FiniteFloat | None = None
    debt_ratio: FiniteFloat | None = None
    rs: FiniteFloat | None = None
    rs_as_of: date | None = None
    rs_base_date: date | None = None
    market_cap: FiniteFloat | None = None
    market_cap_as_of: date | None = None
    per: None = None
    pbr: None = None
