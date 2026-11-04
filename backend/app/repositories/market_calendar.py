from datetime import date, datetime, time, timedelta

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_calendar import MarketCalendarDay
from app.services.market_calendar import KST, TradingCalendar

# 판단에 쓰는 과거 일수. 연휴를 건너뛰어 마지막 마감을 찾기에 충분하다고 생각한 임의의 값
CALENDAR_LOOKBACK_DAYS = 15


async def upsert_days(
    session: AsyncSession, days: list[tuple[date, bool]], fetched_at: datetime
) -> None:
    # 같은 날짜가 두 번 오면 한 문장 안의 ON CONFLICT 가 실패하므로 뒤의 값만 남긴다.
    values = [
        {"day": day, "is_open": is_open, "fetched_at": fetched_at}
        for day, is_open in dict(days).items()
    ]
    if not values:
        return
    statement = insert(MarketCalendarDay).values(values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["day"],
            set_={
                "is_open": statement.excluded.is_open,
                "fetched_at": statement.excluded.fetched_at,
            },
        )
    )


async def fetched_on(session: AsyncSession, day: date) -> bool:
    """그 날짜(KST)에 KIS 에서 받은 기록이 있는지."""
    start = datetime.combine(day, time.min, tzinfo=KST)
    return bool(
        await session.scalar(
            select(
                exists().where(
                    MarketCalendarDay.fetched_at >= start,
                    MarketCalendarDay.fetched_at < start + timedelta(days=1),
                )
            )
        )
    )


async def load_calendar(session: AsyncSession, now: datetime) -> TradingCalendar:
    today = now.astimezone(KST).date()
    rows = (
        await session.execute(
            select(MarketCalendarDay.day, MarketCalendarDay.is_open).where(
                MarketCalendarDay.day >= today - timedelta(days=CALENDAR_LOOKBACK_DAYS),
                MarketCalendarDay.day <= today,
            )
        )
    ).all()
    return TradingCalendar({day: is_open for day, is_open in rows})
