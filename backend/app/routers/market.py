from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.repositories.market import list_snapshots
from app.repositories.ranking import list_rankings
from app.schemas.market import MarketItem, MarketOverview
from app.schemas.ranking import RankingsResponse
from app.services.market_data import INDICATORS
from app.services.market_flow import market_flow_boards
from app.services.ranking import ranking_boards

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/overview", response_model=MarketOverview)
async def overview(session: AsyncSession = Depends(get_session)) -> MarketOverview:
    snapshots = await list_snapshots(session)
    items = []
    for indicator in INDICATORS:
        row = snapshots.get(indicator.code) if indicator.source else None
        status = "pending"
        if indicator.source is None:
            status = "notConfigured"
        elif row and row.value is not None:
            outdated = (
                datetime.now(UTC) - row.collected_at
            ).total_seconds() > indicator.interval * 3
            status = "stale" if row.error_code or outdated else "ready"
        elif row and row.error_code:
            status = "unavailable"
        items.append(
            MarketItem(
                code=indicator.code,
                name=indicator.name,
                source=indicator.source,
                unit=indicator.unit,
                status=status,
                value=float(row.value) if row and row.value is not None else None,
                change=float(row.change) if row and row.change is not None else None,
                as_of=row.observation_date if row else None,
                collected_at=row.collected_at if row else None,
            )
        )
    snapshots = await list_rankings(session)
    flows, sectors = market_flow_boards(snapshots)
    return MarketOverview(
        items=items, rankings=ranking_boards(snapshots), flows=flows, sectors=sectors
    )


@router.get("/rankings", response_model=RankingsResponse)
async def rankings(session: AsyncSession = Depends(get_session)) -> RankingsResponse:
    return RankingsResponse(rankings=ranking_boards(await list_rankings(session)))
