from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import News


async def upsert_news(session: AsyncSession, rows: list[dict]) -> int:
    """URL 이 이미 있으면 건너뛴다. 새로 들어간 행 수를 돌려준다."""
    if not rows:
        return 0
    stmt = insert(News).values(rows).on_conflict_do_nothing(index_elements=["url"])
    result = await session.execute(stmt)
    return result.rowcount
