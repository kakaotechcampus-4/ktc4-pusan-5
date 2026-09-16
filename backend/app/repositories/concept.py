from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Concept

# slug 충돌 시 갱신할 컬럼. id·slug·updated_at 은 제외한다.
_UPDATABLE = (
    "name",
    "aliases",
    "category",
    "extra_categories",
    "summary",
    "body",
    "related",
    "quiz",
    "sources",
    "generated_at",
)


class ConceptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> Sequence[Concept]:
        result = await self.session.execute(select(Concept).order_by(Concept.slug))
        return result.scalars().all()

    async def get_by_slug(self, slug: str) -> Concept | None:
        result = await self.session.execute(select(Concept).where(Concept.slug == slug))
        return result.scalar_one_or_none()

    async def get_names_by_slugs(self, slugs: Sequence[str]) -> dict[str, str]:
        """slug → name. 없는 slug 는 결과에 없다."""
        if not slugs:
            return {}
        result = await self.session.execute(
            select(Concept.slug, Concept.name).where(Concept.slug.in_(list(slugs)))
        )
        return {slug: name for slug, name in result.all()}

    async def upsert_many(self, rows: list[dict[str, Any]]) -> int:
        """slug 가 이미 있으면 갱신한다. 처리한 행 수를 돌려준다."""
        if not rows:
            return 0
        stmt = insert(Concept).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["slug"],
            set_={column: stmt.excluded[column] for column in _UPDATABLE}
            | {"updated_at": func.now()},
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Concept))
        return result.scalar_one()
