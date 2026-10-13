from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import get_current_user
from app.models import User
from app.repositories import watchlist as repo
from app.schemas.watchlist import (
    WatchlistAddRequest,
    WatchlistEntry,
    WatchlistQuote,
    WatchlistResponse,
)
from app.services.quote_freshness import quote_status
from app.services.stock_detail import require_stock

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
Code = Annotated[str, Path(pattern=r"^[0-9A-Z]{6}$")]


@router.get("", response_model=WatchlistResponse)
async def list_watchlist(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WatchlistResponse:
    rows = await repo.list_with_quotes(session, user.id)
    now = datetime.now(UTC)
    return WatchlistResponse(
        items=[
            WatchlistEntry(
                code=stock.code,
                name=stock.name,
                market=stock.market,
                quote=WatchlistQuote.model_validate(quote) if quote else None,
                quote_status=quote_status(quote.collected_at if quote else None, now),
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
    # 종목 상세와 같은 규칙: 서비스 대상(MVP) 종목만 담을 수 있다.
    await require_stock(session, body.stock_code)
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
