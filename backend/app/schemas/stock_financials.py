from typing import Literal

from pydantic import FiniteFloat

from app.schemas.base import CamelModel
from app.schemas.stock import Resource
from app.schemas.stock_investment import InvestmentPoint


class AnnualIncome(CamelModel):
    fiscal_period: str
    revenue: FiniteFloat | None = None
    operating_profit: FiniteFloat | None = None
    net_income: FiniteFloat | None = None


class AnnualEps(CamelModel):
    fiscal_period: str
    eps: FiniteFloat | None = None
    roe: FiniteFloat | None = None
    debt_ratio: FiniteFloat | None = None


class AnnualStability(CamelModel):
    fiscal_period: str
    current_ratio: FiniteFloat | None = None


class FinancialHealth(CamelModel):
    fiscal_period: str
    debt_ratio: FiniteFloat | None = None
    roe: FiniteFloat | None = None
    operating_margin: FiniteFloat | None = None
    current_ratio: FiniteFloat | None = None


class StockFinancials(CamelModel):
    code: str
    source: Literal["KIS"] = "KIS"
    basis: Literal["provider"] = "provider"
    income: Resource[list[AnnualIncome]]
    eps: Resource[list[AnnualEps]]
    health: Resource[FinancialHealth]
    investment: Resource[list[InvestmentPoint]]
