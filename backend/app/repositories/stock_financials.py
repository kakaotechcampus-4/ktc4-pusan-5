from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_financials import StockAnnualEps, StockAnnualIncome

MODELS = {"income": StockAnnualIncome, "eps": StockAnnualEps}


async def list_periods(session: AsyncSession, code: str, resource: str):
    model = MODELS[resource]
    return list(
        (
            await session.scalars(
                select(model)
                .where(model.stock_code == code)
                .order_by(model.period_end.desc())
                .limit(5)
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
    if dates and previous and max(dates) < previous:
        return "OUTDATED_RESPONSE"
    # 전체 스냅샷을 한 트랜잭션에서 교체한다. 정상 빈 응답과 조회 실패는 구별한다.
    await session.execute(delete(model).where(model.stock_code == code))
    if rows:
        await session.execute(
            insert(model).values(
                [{**row, "stock_code": code, "source": "KIS", "collected_at": now} for row in rows]
            )
        )
    return None
