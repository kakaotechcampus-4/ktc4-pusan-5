from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import market


async def test_overview_keeps_six_slots_and_isolates_failures(monkeypatch):
    now = datetime.now(UTC)

    def snapshot(value, error=None, age=0):
        return SimpleNamespace(
            value=value,
            change=Decimal(-1) if value else None,
            observation_date=date(2026, 9, 18) if value else None,
            collected_at=now - timedelta(seconds=age) if value else None,
            error_code=error,
        )

    async def fake_snapshots(session):
        return {
            "kospi": snapshot(Decimal("1234.5")),
            "kosdaq": snapshot(Decimal(800), "UPSTREAM_ERROR"),
            "sp500": snapshot(None, "MISSING_KEY"),
            "usdkrw": snapshot(Decimal(1300), age=1000),
        }

    async def empty_rankings(session):
        return {}

    monkeypatch.setattr(market, "list_snapshots", fake_snapshots)
    monkeypatch.setattr(market, "list_rankings", empty_rankings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/market/overview")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["code"] for item in items] == [
        "kospi",
        "kosdaq",
        "gold",
        "sp500",
        "nasdaq",
        "usdkrw",
    ]
    assert [item["status"] for item in items] == [
        "ready",
        "stale",
        "notConfigured",
        "unavailable",
        "pending",
        "stale",
    ]
    assert items[0]["value"] == 1234.5
    assert items[0]["asOf"] == "2026-09-18"
    assert "collectedAt" in items[0]
    assert items[2]["value"] is None and items[2]["asOf"] is None
