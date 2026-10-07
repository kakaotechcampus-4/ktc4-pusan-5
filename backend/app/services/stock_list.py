"""고정 목록(MVP_STOCKS)을 stock 테이블과 맞춰 순위 순으로 반환한다."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.mvp_stocks import MVP_CODES, MVP_STOCKS
from app.repositories import stock as repo
from app.schemas.stock import StockList, StockListItem


async def stock_list(session: AsyncSession) -> StockList:
    stocks = {stock.code: stock for stock in await repo.listed_by_codes(session, MVP_CODES)}
    if not stocks and await repo.catalog_checked_at(session) is None:
        raise AppError(
            "CATALOG_PENDING", "종목 목록을 준비 중입니다. 잠시 후 다시 시도해주세요.", 503
        )
    return StockList(
        items=[
            StockListItem(
                rank=mvp.rank,
                code=mvp.code,
                name=stocks[mvp.code].name,
                market=stocks[mvp.code].market,
            )
            for mvp in MVP_STOCKS
            if mvp.code in stocks
        ]
    )
