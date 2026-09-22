from datetime import date

import httpx

from app.core.config import settings
from app.services.market_data import MarketDataError, Quote, number


async def fetch_quote(client: httpx.AsyncClient, symbol: str) -> Quote:
    if not settings.fred_api_key:
        raise MarketDataError("MISSING_KEY")
    response = await client.get(
        f"{settings.fred_api_base_url}/series/observations",
        params={
            "api_key": settings.fred_api_key,
            "file_type": "json",
            "series_id": symbol,
            "sort_order": "desc",
            "limit": 30,
        },
    )
    response.raise_for_status()
    rows = [row for row in response.json()["observations"] if row["value"] != "."]
    if len(rows) < 2:
        raise MarketDataError("NO_DATA")
    current, previous = number(rows[0]["value"]), number(rows[1]["value"])
    if previous <= 0:
        raise MarketDataError("INVALID_RESPONSE")
    return Quote(
        current, (current - previous) / previous * 100, date.fromisoformat(rows[0]["date"])
    )
