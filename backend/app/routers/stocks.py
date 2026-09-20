from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.stock import Period, StockOverview, StockPrices
from app.services import stock_detail

router = APIRouter(prefix="/api/stocks", tags=["stocks"])
Code = Annotated[str, Path(pattern=r"^[0-9A-Z]{6}$")]


@router.get("/{code}/overview", response_model=StockOverview)
async def overview(code: Code, session: AsyncSession = Depends(get_session)):
    return await stock_detail.overview(session, code)


@router.get("/{code}/prices", response_model=StockPrices)
async def prices(
    code: Code,
    period: Annotated[Period, Query()] = "1Y",
    session: AsyncSession = Depends(get_session),
):
    return await stock_detail.prices(session, code, period)
