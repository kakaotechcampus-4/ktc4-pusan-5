from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.market import MarketSnapshot
from app.repositories.market import save_result
from app.services.market_data import Quote


async def test_failure_preserves_quote_and_older_data_cannot_roll_it_back():
    async with SessionLocal() as session:
        try:
            now = datetime.now(UTC)
            quote = Quote(Decimal("1250.5"), Decimal("-0.5"), date(2026, 9, 18))
            await save_result(session, "test-market", quote, None, now)
            await save_result(
                session, "test-market", None, "UPSTREAM_HTTP_503", now + timedelta(seconds=60)
            )
            row = await session.scalar(
                select(MarketSnapshot).where(MarketSnapshot.code == "test-market")
            )
            assert row.value == quote.value
            assert row.error_code == "UPSTREAM_HTTP_503"
            assert row.collected_at == now
            assert row.checked_at > row.collected_at
            await save_result(
                session, "test-market", Quote(Decimal(900), Decimal(1), date(2026, 9, 17)), None
            )
            await session.refresh(row)
            assert row.observation_date == quote.observation_date
            assert row.value == quote.value
        finally:
            await session.rollback()
