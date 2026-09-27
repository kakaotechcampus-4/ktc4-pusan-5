"""Validated KIS adapters for lazy stock detail data.

The KIS REST responses contain numeric values as strings.  This module keeps
that parsing at the provider boundary, and deliberately represents unavailable
upstream values as ``None`` rather than manufacturing values.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from app.services.market_data import MarketDataError


class _KisGetter(Protocol):
    async def get(self, path: str, tr_id: str, params: dict[str, str]) -> dict: ...


@dataclass(frozen=True)
class StockSnapshot:
    quote: dict[str, Any] | None
    metrics: dict[str, Decimal | None] | None
    quote_error: str | None = None
    metrics_error: str | None = None


@dataclass(frozen=True)
class DailyPrice:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class StockCatalogItem:
    code: str
    name: str
    market: str
    listed_at: date | None = None


_MARKET_CAP_WON = Decimal(100_000_000)  # KIS hts_avls is in 100 million KRW.
_STOCK_CODE_RE = r"[0-9A-Z]{6}"
_CATALOG_CODE_RE = r"[0-9A-Z]{6}"
_MAX_SAFE_INTEGER = Decimal(9007199254740991)


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _decimal(value: object, *, optional: bool = False) -> Decimal | None:
    raw = _text(value)
    if not raw:
        if optional:
            return None
        raise MarketDataError("INVALID_RESPONSE")
    try:
        result = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        raise MarketDataError("INVALID_RESPONSE") from None
    if not result.is_finite() or abs(result) >= Decimal("1e16"):
        raise MarketDataError("INVALID_RESPONSE")
    return result


def _positive(value: object, *, optional: bool = False) -> Decimal | None:
    result = _decimal(value, optional=optional)
    if result == 0 and optional:
        return None
    if result is not None and result <= 0:
        raise MarketDataError("INVALID_RESPONSE")
    return result


def _integer(value: object, *, optional: bool = False) -> int | None:
    result = _decimal(value, optional=optional)
    if result is None:
        return None
    if result != result.to_integral_value() or result < 0:
        raise MarketDataError("INVALID_RESPONSE")
    try:
        return int(result)
    except (OverflowError, ValueError):
        raise MarketDataError("INVALID_RESPONSE") from None


def _row(body: dict, key: str) -> dict[str, Any]:
    value = body.get(key)
    if not isinstance(value, dict):
        raise MarketDataError("INVALID_RESPONSE")
    return value


async def fetch_snapshot(kis: _KisGetter, code: str) -> StockSnapshot:
    """Fetch and validate one domestic stock's current quote and fundamentals."""
    if not re.fullmatch(_STOCK_CODE_RE, code):
        raise MarketDataError("INVALID_RESPONSE")
    body = await kis.get(
        "/uapi/domestic-stock/v1/quotations/inquire-price",
        "FHKST01010100",
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
    )
    output = _row(body, "output")
    quote: dict[str, Any] | None = None
    quote_error: str | None = None
    try:
        price = _positive(output.get("stck_prpr"))
        change_amount = _decimal(output.get("prdy_vrss"))
        change = _decimal(output.get("prdy_ctrt"))
        volume = _integer(output.get("acml_vol"))
        trading_value = _decimal(output.get("acml_tr_pbmn"))
        market_cap_raw = _positive(output.get("hts_avls"), optional=True)
        market_cap = market_cap_raw * _MARKET_CAP_WON if market_cap_raw is not None else None
        if market_cap is not None and market_cap > _MAX_SAFE_INTEGER:
            raise MarketDataError("INVALID_RESPONSE")
        if change_amount is None or change is None or volume is None or trading_value is None or trading_value < 0:
            raise MarketDataError("INVALID_RESPONSE")
        quote = {"price": price, "change": change, "change_amount": change_amount, "volume": volume,
                 "trading_value": trading_value, "market_cap": market_cap, "source_as_of": None}
    except MarketDataError as error:
        quote_error = str(error)
    metrics: dict[str, Decimal | None] | None = None
    metrics_error: str | None = None
    try:
        metrics = {"per": _decimal(output.get("per"), optional=True), "pbr": _decimal(output.get("pbr"), optional=True),
                   "eps": _decimal(output.get("eps"), optional=True), "bps": _decimal(output.get("bps"), optional=True),
                   "foreign_ownership": _decimal(output.get("hts_frgn_ehrt"), optional=True),
                   "week52_high": _positive(output.get("w52_hgpr"), optional=True),
                   "week52_low": _positive(output.get("w52_lwpr"), optional=True)}
        if metrics["foreign_ownership"] is not None and not 0 <= metrics["foreign_ownership"] <= 100:
            raise MarketDataError("INVALID_RESPONSE")
    except MarketDataError as error:
        metrics_error = str(error)
        metrics = None
    return StockSnapshot(
        quote=quote,
        metrics=metrics,
        quote_error=quote_error,
        metrics_error=metrics_error,
    )


def _trade_date(raw: object) -> date:
    value = _text(raw)
    if not re.fullmatch(r"\d{8}", value):
        raise MarketDataError("INVALID_RESPONSE")
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    except ValueError:
        raise MarketDataError("INVALID_RESPONSE") from None


async def fetch_prices(kis: _KisGetter, code: str, start: date, end: date) -> list[DailyPrice]:
    """Fetch daily unadjusted prices (the caller chunks ranges to KIS limits)."""
    if not re.fullmatch(_STOCK_CODE_RE, code) or not isinstance(start, date) or not isinstance(end, date):
        raise MarketDataError("INVALID_RESPONSE")
    if start > end:
        raise MarketDataError("INVALID_RESPONSE")
    body = await kis.get(
        "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        "FHKST03010100",
        {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",
        },
    )
    raw_rows = body.get("output2")
    if not isinstance(raw_rows, list) or any(not isinstance(row, dict) for row in raw_rows):
        raise MarketDataError("INVALID_RESPONSE")
    result: list[DailyPrice] = []
    seen: set[date] = set()
    for row in raw_rows:
        if not _text(row.get("stck_bsop_date")):
            continue
        trade_date = _trade_date(row.get("stck_bsop_date"))
        if not start <= trade_date <= end or trade_date in seen:
            raise MarketDataError("INVALID_RESPONSE")
        seen.add(trade_date)
        values = [_decimal(row.get(key)) for key in ("stck_oprc", "stck_hgpr", "stck_lwpr", "stck_clpr")]
        volume = _integer(row.get("acml_vol"))
        if volume is None or any(value is None for value in values):
            raise MarketDataError("INVALID_RESPONSE")
        opening, high, low, closing = values
        # KIS can represent a halted/non-trading session as four zero OHLC
        # values. Preserve that upstream fact; reject partially-zero candles.
        if any(value < 0 for value in values) or (any(value == 0 for value in values) and not all(value == 0 for value in values)):
            raise MarketDataError("INVALID_RESPONSE")
        if not (low <= opening <= high and low <= closing <= high):
            raise MarketDataError("INVALID_RESPONSE")
        result.append(DailyPrice(trade_date, opening, high, low, closing, volume))
    return sorted(result, key=lambda row: row.trade_date)


def _parse_master_zip(content: bytes, market: str) -> list[StockCatalogItem]:
    # The official examples slice 228/222 characters including the line ending;
    # splitlines() removes that ending, leaving 227/221 data characters.
    tail_length, listed_offset = ((227, 105) if market == "KOSPI" else (221, 100))
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise MarketDataError("INVALID_RESPONSE")
            text = archive.read(names[0]).decode("cp949")
    except (zipfile.BadZipFile, UnicodeDecodeError, OSError):
        raise MarketDataError("INVALID_RESPONSE") from None
    items: list[StockCatalogItem] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if len(line) <= tail_length:
            continue
        head = line[: len(line) - tail_length]
        code = head[:9].strip()
        if not re.fullmatch(_CATALOG_CODE_RE, code):
            continue
        # Official KIS files have a variable head and a market-specific fixed tail.
        name = head[21:].strip()
        if not name or code in seen:
            raise MarketDataError("INVALID_RESPONSE")
        seen.add(code)
        listed_at = None
        listed_raw = line[len(line) - tail_length + listed_offset : len(line) - tail_length + listed_offset + 8]
        if listed_raw.strip():
            try:
                listed_at = date.fromisoformat(
                    f"{listed_raw[:4]}-{listed_raw[4:6]}-{listed_raw[6:8]}"
                )
            except ValueError:
                raise MarketDataError("INVALID_RESPONSE") from None
        items.append(StockCatalogItem(code, name, market, listed_at))
    if not items:
        raise MarketDataError("NO_DATA")
    return items


async def fetch_catalog(client: Any) -> list[StockCatalogItem]:
    """Download both official KIS master files and return an all-or-nothing catalog."""
    http = getattr(client, "client", client)
    urls = (
        ("KOSPI", "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"),
        ("KOSDAQ", "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip"),
    )
    all_items: list[StockCatalogItem] = []
    seen: set[str] = set()
    try:
        for market, url in urls:
            response = await http.get(url)
            response.raise_for_status()
            items = _parse_master_zip(response.content, market)
            if any(item.code in seen for item in items):
                raise MarketDataError("INVALID_RESPONSE")
            seen.update(item.code for item in items)
            all_items.extend(items)
    except MarketDataError:
        raise
    except (httpx.HTTPError, OSError, AttributeError, TypeError, ValueError):
        raise MarketDataError("UPSTREAM_ERROR") from None
    if not all_items:
        raise MarketDataError("NO_DATA")
    return all_items
