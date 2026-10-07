from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Stock, StockQuoteSnapshot, WatchlistItem


async def list_with_quotes(session: AsyncSession, user_id: int):
    result = await session.execute(
        select(Stock, StockQuoteSnapshot)
        .join(WatchlistItem, WatchlistItem.stock_code == Stock.code)
        .outerjoin(StockQuoteSnapshot, StockQuoteSnapshot.stock_code == Stock.code)
        .where(WatchlistItem.user_id == user_id)
        .order_by(WatchlistItem.created_at.desc(), WatchlistItem.id.desc())
    )
    return result.all()


async def stock_exists(session: AsyncSession, code: str) -> bool:
    return await session.get(Stock, code) is not None


# 이미 담긴 종목이면 무시
async def add(session: AsyncSession, user_id: int, code: str) -> None:
    await session.execute(
        pg_insert(WatchlistItem)
        .values(user_id=user_id, stock_code=code)
        .on_conflict_do_nothing(constraint="uq_watchlist_item_user_stock")
    )


async def remove(session: AsyncSession, user_id: int, code: str) -> None:
    await session.execute(
        delete(WatchlistItem).where(
            WatchlistItem.user_id == user_id, WatchlistItem.stock_code == code
        )
    )
