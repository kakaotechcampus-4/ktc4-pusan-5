from datetime import UTC, datetime

from sqlalchemy import case, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market import MarketSnapshot
from app.services.market_data import Quote


async def list_snapshots(session: AsyncSession) -> dict[str, MarketSnapshot]:
    rows = (await session.scalars(select(MarketSnapshot))).all()
    return {row.code: row for row in rows}


async def save_result(
    session: AsyncSession,
    code: str,
    quote: Quote | None,
    error_code: str | None,
    checked_at: datetime | None = None,
) -> None:
    now = checked_at or datetime.now(UTC)
    values = {"code": code, "checked_at": now, "error_code": error_code}
    if quote:
        values.update(
            value=quote.value,
            change=quote.change,
            observation_date=quote.observation_date,
            collected_at=now,
        )
    statement = insert(MarketSnapshot).values(**values)
    updates = {key: value for key, value in values.items() if key != "code"}
    # 이전 기준일의 응답이 마지막 정상값을 덮어쓰지 않도록 한다.
    if quote:
        is_newer = or_(
            MarketSnapshot.observation_date.is_(None),
            MarketSnapshot.observation_date <= quote.observation_date,
        )
        for key in ("value", "change", "observation_date", "collected_at"):
            updates[key] = case(
                (is_newer, getattr(statement.excluded, key)), else_=getattr(MarketSnapshot, key)
            )
    await session.execute(statement.on_conflict_do_update(index_elements=["code"], set_=updates))
