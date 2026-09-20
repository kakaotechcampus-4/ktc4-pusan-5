"""KIS 연간 조회 어댑터. 최신 중간결산이 포함될 수 있어 결산연월을 보존한다."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.services.market_data import MarketDataError

_WON_PER_EOK = Decimal(100_000_000)
_NUMERIC_24_8_MAX = Decimal("9999999999999999.99999999")


class _Getter(Protocol):
    async def get(self, path: str, tr_id: str, params: dict[str, str]) -> dict: ...


@dataclass(frozen=True)
class AnnualIncome:
    period_end: date
    revenue: Decimal | None
    operating_profit: Decimal | None
    net_income: Decimal | None


@dataclass(frozen=True)
class AnnualEps:
    period_end: date
    eps: Decimal | None
    roe: Decimal | None = None
    debt_ratio: Decimal | None = None


@dataclass(frozen=True)
class AnnualStability:
    period_end: date
    current_ratio: Decimal | None


def _period(raw: object) -> date:
    value = str(raw or "").strip()
    if not re.fullmatch(r"\d{6}", value):
        raise MarketDataError("INVALID_RESPONSE")
    year, month = int(value[:4]), int(value[4:])
    if not 1900 <= year <= 9999 or not 1 <= month <= 12:
        raise MarketDataError("INVALID_RESPONSE")
    return date(year, month, calendar.monthrange(year, month)[1])


def _number(raw: object) -> Decimal | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        result = Decimal(value.replace(",", ""))
    except InvalidOperation:
        raise MarketDataError("INVALID_RESPONSE") from None
    if not result.is_finite() or abs(result) >= Decimal("1e16"):
        raise MarketDataError("INVALID_RESPONSE")
    return result


def _income_won(raw: object) -> Decimal | None:
    value = _number(raw)
    if value is None:
        return None
    result = value * _WON_PER_EOK
    if abs(result) > _NUMERIC_24_8_MAX:
        raise MarketDataError("INVALID_RESPONSE")
    return result


def _rows(body: dict) -> list[dict]:
    output = body.get("output")
    if isinstance(output, dict):
        return [output]
    if (
        isinstance(output, list)
        and len(output) <= 100
        and all(isinstance(row, dict) for row in output)
    ):
        return output
    raise MarketDataError("INVALID_RESPONSE")


async def fetch_income(kis: _Getter, code: str) -> list[AnnualIncome]:
    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        raise MarketDataError("INVALID_RESPONSE")
    body = await kis.get(
        "/uapi/domestic-stock/v1/finance/income-statement",
        "FHKST66430200",
        {"FID_DIV_CLS_CODE": "0", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
    )
    result: list[AnnualIncome] = []
    seen: set[date] = set()
    for row in _rows(body):
        if not any(field in row for field in ("sale_account", "bsop_prti", "thtr_ntin")):
            raise MarketDataError("INVALID_RESPONSE")
        period = _period(row.get("stac_yymm"))
        if period in seen:
            raise MarketDataError("INVALID_RESPONSE")
        seen.add(period)
        result.append(
            AnnualIncome(
                period,
                _income_won(row.get("sale_account")),
                _income_won(row.get("bsop_prti")),
                _income_won(row.get("thtr_ntin")),
            )
        )
    return sorted(result, key=lambda x: x.period_end)


async def fetch_eps(kis: _Getter, code: str) -> list[AnnualEps]:
    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        raise MarketDataError("INVALID_RESPONSE")
    body = await kis.get(
        "/uapi/domestic-stock/v1/finance/financial-ratio",
        "FHKST66430300",
        {"FID_DIV_CLS_CODE": "0", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
    )
    result: list[AnnualEps] = []
    seen: set[date] = set()
    for row in _rows(body):
        if "eps" not in row:
            raise MarketDataError("INVALID_RESPONSE")
        period = _period(row.get("stac_yymm"))
        if period in seen:
            raise MarketDataError("INVALID_RESPONSE")
        seen.add(period)
        result.append(
            AnnualEps(
                period,
                _number(row.get("eps")),
                _number(row.get("roe_val")),
                _number(row.get("lblt_rate")),
            )
        )
    return sorted(result, key=lambda x: x.period_end)


async def fetch_stability(kis: _Getter, code: str) -> list[AnnualStability]:
    if not re.fullmatch(r"[0-9A-Z]{6}", code):
        raise MarketDataError("INVALID_RESPONSE")
    body = await kis.get(
        "/uapi/domestic-stock/v1/finance/stability-ratio",
        "FHKST66430600",
        {"FID_DIV_CLS_CODE": "0", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
    )
    result: list[AnnualStability] = []
    seen: set[date] = set()
    for row in _rows(body):
        if "crnt_rate" not in row:
            raise MarketDataError("INVALID_RESPONSE")
        period = _period(row.get("stac_yymm"))
        if period in seen:
            raise MarketDataError("INVALID_RESPONSE")
        seen.add(period)
        result.append(AnnualStability(period, _number(row.get("crnt_rate"))))
    return sorted(result, key=lambda x: x.period_end)
