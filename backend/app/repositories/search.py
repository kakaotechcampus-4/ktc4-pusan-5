from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Concept, Stock

_ESCAPE = "\\"


def _escape_like(text: str) -> str:
    # 사용자가 입력한 % _ 가 LIKE 패턴으로 해석되지 않게 한다.
    return text.replace(_ESCAPE, _ESCAPE * 2).replace("%", _ESCAPE + "%").replace("_", _ESCAPE + "_")


async def search_stocks(
    session: AsyncSession, query: str, limit: int, codes: frozenset[str]
) -> list[Stock]:
    """codes 에 포함된 종목 안에서만 검색한다."""
    escaped = _escape_like(query)
    contains = f"%{escaped}%"
    prefix = f"{escaped}%"
    # 이름이 정확히 같음 → 코드 앞부분 일치 → 이름 앞부분 일치 → 이름에 포함 순서
    rank = case(
        (func.lower(Stock.name) == query.lower(), 0),
        (Stock.code.ilike(prefix, escape=_ESCAPE), 1),
        (Stock.name.ilike(prefix, escape=_ESCAPE), 2),
        else_=3,
    )
    result = await session.execute(
        select(Stock)
        .where(
            Stock.listing_status == "listed",
            Stock.code.in_(codes),
            or_(Stock.name.ilike(contains, escape=_ESCAPE), Stock.code.ilike(prefix, escape=_ESCAPE)),
        )
        .order_by(rank, func.length(Stock.name), Stock.name)
        .limit(limit)
    )
    return list(result.scalars().all())


async def search_concepts(session: AsyncSession, query: str, limit: int) -> list[Concept]:
    escaped = _escape_like(query)
    contains = f"%{escaped}%"
    prefix = f"{escaped}%"
    aliases = func.jsonb_array_elements_text(Concept.aliases).table_valued("value")
    alias_matches = (
        select(literal(1))
        .select_from(aliases)
        .where(aliases.c.value.ilike(contains, escape=_ESCAPE))
        .correlate(Concept)
        .exists()
    )
    rank = case(
        (func.lower(Concept.name) == query.lower(), 0),
        (Concept.name.ilike(prefix, escape=_ESCAPE), 1),
        (Concept.name.ilike(contains, escape=_ESCAPE), 2),
        else_=3,  # 별칭으로만 일치
    )
    result = await session.execute(
        select(Concept)
        .where(or_(Concept.name.ilike(contains, escape=_ESCAPE), alias_matches))
        .order_by(rank, func.length(Concept.name), Concept.name)
        .limit(limit)
    )
    return list(result.scalars().all())
