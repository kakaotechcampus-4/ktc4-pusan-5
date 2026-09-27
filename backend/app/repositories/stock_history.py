from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models.stock_history import StockPeriodMarket

HISTORY_TTL = timedelta(days=7)


async def save_history(session, code, period, kind, data, now):
    values = {"stock_code": code, "period_end": period}
    if kind == "history_cap":
        values.update(market_cap=None, cap_as_of=None, cap_collected_at=now)
    else:
        values.update(rs=None, rs_as_of=None, rs_base_date=None, rs_collected_at=now)
    values.update(data or {})
    statement = insert(StockPeriodMarket).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["stock_code", "period_end"],
            set_={
                k: statement.excluded[k] for k in values if k not in ("stock_code", "period_end")
            },
        )
    )


async def history_for(session, code):
    return {
        row.period_end: row
        for row in (
            await session.scalars(
                select(StockPeriodMarket).where(StockPeriodMarket.stock_code == code)
            )
        ).all()
    }
