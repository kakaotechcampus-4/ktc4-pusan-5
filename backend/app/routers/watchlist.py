from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import get_current_user
from app.core.errors import AppError
from app.models import User
from app.repositories import watchlist as repo
from app.schemas.watchlist import (
    WatchlistAddRequest,
    WatchlistEntry,
    WatchlistQuote,
    WatchlistResponse,
)

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
Code = Annotated[str, Path(pattern=r"^[0-9A-Z]{6}$")]


@router.get("", response_model=WatchlistResponse)
async def list_watchlist(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchlistResponse:
    rows = await repo.list_with_quotes(session, user.id)
    return WatchlistResponse(
        items=[
            WatchlistEntry(
                code=stock.code,
                name=stock.name,
                market=stock.market,
                quote=WatchlistQuote.model_validate(quote) if quote else None,
                as_of=(quote.source_as_of or quote.collected_at) if quote else None,
            )
            for stock, quote in rows
        ]
    )


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def add_watchlist(
    body: WatchlistAddRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if not await repo.stock_exists(session, body.stock_code):
        raise AppError("STOCK_NOT_FOUND", "종목을 찾을 수 없습니다", status_code=404)
    await repo.add(session, user.id, body.stock_code)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_watchlist(
    code: Code,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await repo.remove(session, user.id, code)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
