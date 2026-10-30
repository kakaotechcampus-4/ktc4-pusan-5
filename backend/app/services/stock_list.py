"""고정 목록(MVP_STOCKS)을 stock 테이블과 맞춰 순위 순으로 반환한다."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.mvp_stocks import MVP_CODES, MVP_STOCKS, MVP_STOCKS_AS_OF
from app.repositories import stock as repo
from app.schemas.stock import StockList, StockListItem

logger = logging.getLogger(__name__)


async def stock_list(session: AsyncSession) -> StockList:
    rows = {stock.code: stock for stock in await repo.by_codes(session, MVP_CODES)}
    stocks = {code: stock for code, stock in rows.items() if stock.listing_status == "listed"}
    if not stocks and await repo.catalog_checked_at(session) is None:
        raise AppError(
            "CATALOG_PENDING", "종목 목록을 준비 중입니다. 잠시 후 다시 시도해주세요.", 503
        )
    missing_codes = [mvp.code for mvp in MVP_STOCKS if mvp.code not in stocks]
    if missing_codes:
        not_in_db = [code for code in missing_codes if code not in rows]
        inactive = [code for code in missing_codes if code in rows]
        logger.warning(
            "mvp stock catalog incomplete: missing=%d total=%d not_in_db=%s inactive=%s",
            len(missing_codes),
            len(MVP_STOCKS),
            not_in_db,
            inactive,
        )
    return StockList(
        items=[
            StockListItem(
                rank=mvp.rank,
                code=mvp.code,
                name=stocks[mvp.code].name,
                market=stocks[mvp.code].market,
                sector=mvp.sector,
            )
            for mvp in MVP_STOCKS
            if mvp.code in stocks
        ],
        complete=not missing_codes,
        as_of=MVP_STOCKS_AS_OF,
    )
