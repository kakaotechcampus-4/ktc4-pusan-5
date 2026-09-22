from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_financials import (
    StockAnnualEps,
    StockAnnualIncome,
    StockAnnualStability,
    StockQuarterlyIncome,
    StockQuarterlyRatio,
)

MODELS = {
    "income": StockAnnualIncome,
    "eps": StockAnnualEps,
    "stability": StockAnnualStability,
    "quarter_income": StockQuarterlyIncome,
    "quarter_ratios": StockQuarterlyRatio,
}


async def list_periods(session: AsyncSession, code: str, resource: str, limit: int = 5):
    model = MODELS[resource]
    return list(
        (
            await session.scalars(
                select(model)
                .where(model.stock_code == code)
                .order_by(model.period_end.desc())
                .limit(limit)
            )
        ).all()
    )


async def save_periods(
    session: AsyncSession, code: str, resource: str, rows: list[dict], now: datetime
) -> str | None:
    model = MODELS[resource]
    dates = [row["period_end"] for row in rows]
    if len(set(dates)) != len(dates) or any(not isinstance(day, date) for day in dates):
        raise ValueError("INVALID_PERIODS")
    previous = await session.scalar(
        select(func.max(model.period_end)).where(model.stock_code == code)
    )
    if not dates:
        # An empty response is a valid empty snapshot only for a stock with no
        # previously collected periods. Never erase a usable snapshot because
        # an upstream endpoint temporarily returned no rows.
        return "EMPTY_RESPONSE" if previous else None
    if dates and previous and max(dates) < previous:
        return "OUTDATED_RESPONSE"
    # Upsert each returned period. Providers may omit older periods or return
    # explicit null corrections; neither should delete unrelated history.
    values = [{**row, "stock_code": code, "source": "KIS", "collected_at": now} for row in rows]
    statement = insert(model).values(values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["stock_code", "period_end"],
            set_={
                key: statement.excluded[key]
                for key in values[0]
                if key not in ("stock_code", "period_end")
            }
        )
    )
    return None
