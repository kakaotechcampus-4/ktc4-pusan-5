from typing import Literal

from pydantic import FiniteFloat

from app.schemas.base import CamelModel
from app.schemas.stock import Resource


class AnnualIncome(CamelModel):
    fiscal_period: str
    revenue: FiniteFloat | None = None
    operating_profit: FiniteFloat | None = None
    net_income: FiniteFloat | None = None


class AnnualEps(CamelModel):
    fiscal_period: str
    eps: FiniteFloat | None = None


class StockFinancials(CamelModel):
    code: str
    source: Literal["KIS"] = "KIS"
    basis: Literal["provider"] = "provider"
    income: Resource[list[AnnualIncome]]
    eps: Resource[list[AnnualEps]]
