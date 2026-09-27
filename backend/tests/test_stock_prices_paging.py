from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.errors import AppError
from app.main import app
from app.services.stock_detail import requested_range
from tests.test_stock_detail import stock_db  # noqa: F401 -- shared pytest fixture


def test_from_date_extends_default_range_and_clamps_to_listing():
    start, end = requested_range("1Y", date(2020, 1, 1), date(2026, 9, 20), date(2024, 1, 1))
    assert start == date(2024, 1, 1)
    assert end == date(2026, 9, 19)


def test_from_date_before_listing_is_clamped():
    start, _ = requested_range("ALL", date(2025, 1, 1), date(2026, 9, 20), date(1990, 1, 1))
    assert start == date(2025, 1, 1)


def test_unknown_listing_uses_supported_history_floor():
    start, _ = requested_range("ALL", None, date(2026, 9, 20), date(1900, 1, 1))
    assert start == date(1990, 1, 1)


def test_future_from_date_is_unprocessable():
    with pytest.raises(AppError) as exc:
        requested_range("1Y", date(2020, 1, 1), date(2026, 9, 20), date(2026, 9, 20))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.usefixtures("stock_db")
async def test_prices_api_accepts_from_date_alias_and_extends_coverage():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/stocks/TST001/prices?period=1M&fromDate=2024-01-01")
    assert response.status_code == 200
    body = response.json()
    assert body["coverage"]["fromDate"] == "2024-01-01"
    assert body["coverage"]["toDate"] > "2024-01-01"


@pytest.mark.asyncio
@pytest.mark.usefixtures("stock_db")
async def test_prices_api_rejects_invalid_from_date():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/stocks/TST001/prices?fromDate=not-a-date")
    assert response.status_code == 422
