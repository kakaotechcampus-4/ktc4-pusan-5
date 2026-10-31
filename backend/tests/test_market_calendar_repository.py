from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.models.market_calendar import MarketCalendarDay
from app.repositories.market_calendar import fetched_on, load_calendar, upsert_days
from app.services.market_calendar import KST

# 운영 수집기가 넣은 행과 겹치지 않도록 먼 과거 날짜를 쓴다.
DAY = date(2001, 3, 1)


async def test_upsert_overwrites_day_and_records_fetch_date():
    async with SessionLocal() as session:
        try:
            first = datetime(2001, 3, 1, 8, 0, tzinfo=KST)
            await upsert_days(session, [(DAY, True)], first)
            # 다음 날 받은 값이 같은 날짜를 덮어쓴다. 같은 날짜가 두 번 와도 실패하지 않는다.
            second = datetime(2001, 3, 2, 0, 30, tzinfo=KST)
            await upsert_days(session, [(DAY, True), (DAY, False)], second)
            row = await session.get(MarketCalendarDay, DAY)
            await session.refresh(row)
            assert row.is_open is False
            assert row.fetched_at == second

            assert await fetched_on(session, date(2001, 3, 2)) is True
            assert await fetched_on(session, date(2001, 3, 1)) is False  # 덮어써져 남지 않음
            assert await fetched_on(session, date(2001, 3, 3)) is False
        finally:
            await session.rollback()


async def test_load_calendar_reads_recent_days_only():
    async with SessionLocal() as session:
        try:
            fetched = datetime(2001, 3, 1, 8, 0, tzinfo=KST)
            await upsert_days(
                session,
                [
                    (DAY - timedelta(days=16), False),  # 범위 밖(15일 전보다 과거)
                    (DAY - timedelta(days=15), False),
                    (DAY, True),
                    (DAY + timedelta(days=1), False),  # 내일은 읽지 않는다
                ],
                fetched,
            )
            calendar = await load_calendar(session, datetime(2001, 3, 1, 10, 0, tzinfo=KST))
            assert dict(calendar.days) == {DAY - timedelta(days=15): False, DAY: True}
        finally:
            await session.rollback()
