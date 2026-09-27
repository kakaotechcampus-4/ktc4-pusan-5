from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.stock_history import KrxHistoricalCache
from app.repositories.stock_history import HISTORY_TTL
from app.services.market_data import MarketDataError


async def krx_rows(client, market, kind, trade_date):
    """종목별 요청이 동일 시장의 전체 일별 응답을 중복 다운로드하지 않게 한다."""
    now = datetime.now(UTC)
    key = (market, kind, trade_date)
    async with SessionLocal() as session:
        saved = await session.get(KrxHistoricalCache, key)
        if saved and now - saved.collected_at < (HISTORY_TTL if saved.rows else timedelta(days=1)):
            return saved.rows
    if not settings.krx_auth_key:
        raise MarketDataError("MISSING_KEY")
    endpoints = {
        ("KOSPI", "stock"): "sto/stk_bydd_trd",
        ("KOSDAQ", "stock"): "sto/ksq_bydd_trd",
        ("KOSPI", "index"): "idx/kospi_dd_trd",
        ("KOSDAQ", "index"): "idx/kosdaq_dd_trd",
    }
    response = await client.get(
        settings.krx_api_base_url + "/" + endpoints[(market, kind)],
        headers={"AUTH_KEY": settings.krx_auth_key},
        params={"basDd": trade_date.strftime("%Y%m%d")},
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise MarketDataError("INVALID_RESPONSE")
    rows = body.get("OutBlock_1")
    if (
        not isinstance(rows, list)
        or len(rows) > 10000
        or any(
            not isinstance(row, dict)
            or str(row.get("BAS_DD", "")).replace("-", "") != trade_date.strftime("%Y%m%d")
            for row in rows
        )
    ):
        raise MarketDataError("INVALID_RESPONSE")
    async with SessionLocal() as session:
        statement = insert(KrxHistoricalCache).values(
            market=market, kind=kind, trade_date=trade_date, rows=rows, collected_at=now
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["market", "kind", "trade_date"],
                set_={"rows": statement.excluded.rows, "collected_at": now},
            )
        )
        await session.commit()
    return rows
