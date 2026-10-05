from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.repositories import search as repo
from app.schemas.search import ConceptSearchItem, SearchResponse, StockSearchItem

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search(
    q: Annotated[str, Query(min_length=1, max_length=50)],
    limit: Annotated[int, Query(ge=1, le=20, description="종류별 최대 개수")] = 6,
    session: AsyncSession = Depends(get_session),
) -> SearchResponse:
    query = q.strip()
    if not query:
        return SearchResponse(query=query, stocks=[], concepts=[])
    stocks = await repo.search_stocks(session, query, limit)
    concepts = await repo.search_concepts(session, query, limit)
    return SearchResponse(
        query=query,
        stocks=[StockSearchItem.model_validate(stock) for stock in stocks],
        concepts=[ConceptSearchItem.model_validate(concept) for concept in concepts],
    )
