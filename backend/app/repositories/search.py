from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Concept, Stock

_ESCAPE = "\\"


def _escape_like(text: str) -> str:
    # 사용자가 입력한 % _ 가 LIKE 패턴으로 해석되지 않게 한다.
    return text.replace(_ESCAPE, _ESCAPE * 2).replace("%", _ESCAPE + "%").replace("_", _ESCAPE + "_")


def _squash(text: str) -> str:
    # 공백을 모두 없앤다. "삼성 전자", "삼성   전자", "삼성전자" 를 같은 검색어로 본다.
    return "".join(text.split())


def _no_space(column):
    # DB 값도 같은 기준으로 비교한다.
    return func.replace(column, " ", "")


async def search_stocks(
    session: AsyncSession, query: str, limit: int, codes: frozenset[str]
) -> list[Stock]:
    """codes 에 포함된 종목 안에서만 검색한다."""
    needle = _squash(query)
    escaped = _escape_like(needle)
    contains = f"%{escaped}%"
    prefix = f"{escaped}%"
    name = _no_space(Stock.name)
    # 이름이 정확히 같음 → 코드 앞부분 일치 → 이름 앞부분 일치 → 이름에 포함 순서 (공백 무시)
    rank = case(
        (func.lower(name) == needle.lower(), 0),
        (Stock.code.ilike(prefix, escape=_ESCAPE), 1),
        (name.ilike(prefix, escape=_ESCAPE), 2),
        else_=3,
    )
    result = await session.execute(
        select(Stock)
        .where(
            Stock.listing_status == "listed",
            Stock.code.in_(codes),
            or_(name.ilike(contains, escape=_ESCAPE), Stock.code.ilike(prefix, escape=_ESCAPE)),
        )
        .order_by(rank, func.length(Stock.name), Stock.name)
        .limit(limit)
    )
    return list(result.scalars().all())


async def search_concepts(session: AsyncSession, query: str, limit: int) -> list[Concept]:
    needle = _squash(query)
    escaped = _escape_like(needle)
    contains = f"%{escaped}%"
    prefix = f"{escaped}%"
    name = _no_space(Concept.name)
    aliases = func.jsonb_array_elements_text(Concept.aliases).table_valued("value")
    alias_matches = (
        select(literal(1))
        .select_from(aliases)
        .where(_no_space(aliases.c.value).ilike(contains, escape=_ESCAPE))
        .correlate(Concept)
        .exists()
    )
    rank = case(
        (func.lower(name) == needle.lower(), 0),
        (name.ilike(prefix, escape=_ESCAPE), 1),
        (name.ilike(contains, escape=_ESCAPE), 2),
        else_=3,  # 별칭으로만 일치
    )
    result = await session.execute(
        select(Concept)
        .where(or_(name.ilike(contains, escape=_ESCAPE), alias_matches))
        .order_by(rank, func.length(Concept.name), Concept.name)
        .limit(limit)
    )
    return list(result.scalars().all())
