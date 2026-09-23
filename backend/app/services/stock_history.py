"""Historical market-cap and relative-strength provider adapters."""

from __future__ import annotations

import calendar
import re
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.market_data import MarketDataError

Cache = Callable[[str, str, date], Awaitable[list[dict[str, Any]]]]
_MAX = Decimal("1e16")


def _num(value: object, *, allow_zero: bool = True) -> Decimal:
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise MarketDataError("INVALID_RESPONSE") from None
    if (
        not result.is_finite()
        or abs(result) >= _MAX
        or (not allow_zero and result <= 0)
        or result < 0
    ):
        raise MarketDataError("INVALID_RESPONSE")
    return result


def _code(value: object) -> str:
    return str(value or "").strip()


def _row_date(row: dict[str, Any], key: str) -> date:
    raw = _code(row.get(key))
    try:
        if re.fullmatch(r"\d{8}", raw):
            return date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")
        return date.fromisoformat(raw)
    except ValueError:
        raise MarketDataError("INVALID_RESPONSE") from None


async def fetch_cap(
    client: Any, code: str, market: str, period_end: date, cache: Cache
) -> dict | None:
    if not re.fullmatch(r"[0-9A-Z]{6}", code) or market not in ("KOSPI", "KOSDAQ"):
        raise MarketDataError("INVALID_RESPONSE")
    for offset in range(15):
        day = period_end - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        rows = await cache(market, "stock", day)
        if not rows:
            continue
        matches = [row for row in rows if _code(row.get("ISU_CD", row.get("isu_cd"))) == code]
        if not matches:
            return None
        if len(matches) != 1:
            raise MarketDataError("INVALID_RESPONSE")
        row = matches[0]
        actual = _row_date(row, "BAS_DD")
        if actual != day:
            raise MarketDataError("INVALID_RESPONSE")
        return {"market_cap": _num(row.get("MKTCAP", row.get("mktcap"))), "cap_as_of": actual}
    return None


def _year_prior(value: date) -> date:
    day = min(value.day, calendar.monthrange(value.year - 1, value.month)[1])
    return value.replace(year=value.year - 1, day=day)


async def fetch_rs(kis: Any, code: str, market: str, period_end: date, cache: Cache) -> dict | None:
    if not re.fullmatch(r"[0-9A-Z]{6}", code) or market not in ("KOSPI", "KOSDAQ"):
        raise MarketDataError("INVALID_RESPONSE")

    async def close_at(target):
        start = target - timedelta(days=14)
        body = await kis.get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "FHKST03010100",
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": target.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        rows = body.get("output2")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise MarketDataError("INVALID_RESPONSE")
        prices = {}
        for row in rows:
            if not _code(row.get("stck_bsop_date")):
                continue
            day = _row_date(row, "stck_bsop_date")
            if not start <= day <= target or day in prices:
                raise MarketDataError("INVALID_RESPONSE")
            prices[day] = _num(row.get("stck_clpr"))
        if not prices:
            return None
        latest = max(prices)
        return (latest, prices[latest]) if prices[latest] > 0 else None

    end = await close_at(period_end)
    if end is None:
        return None
    start = await close_at(_year_prior(end[0]))
    if start is None:
        return None
    end_day, end_price = end
    start_day, start_price = start
    index_name = "KOSPI" if market == "KOSPI" else "KOSDAQ"
    end_rows = await cache(market, "index", end_day)
    start_rows = await cache(market, "index", start_day)

    def index_price(items: list[dict[str, Any]], day: date) -> Decimal:
        for row in items:
            if _code(row.get("IDX_NM", row.get("idx_nm"))) in (
                index_name,
                ("코스피" if market == "KOSPI" else "코스닥"),
            ):
                if _row_date(row, "BAS_DD") != day:
                    raise MarketDataError("INVALID_RESPONSE")
                return _num(row.get("CLSPRC_IDX", row.get("clsprc_idx")), allow_zero=False)
        raise MarketDataError("NO_DATA")

    try:
        ie, ib = index_price(end_rows, end_day), index_price(start_rows, start_day)
    except MarketDataError as error:
        if str(error) == "NO_DATA":
            return None
        raise
    rs = ((end_price / start_price - 1) - (ie / ib - 1)) * 100
    if not rs.is_finite() or abs(rs) >= _MAX:
        raise MarketDataError("INVALID_RESPONSE")
    return {"rs": rs, "rs_as_of": end_day, "rs_base_date": start_day}
