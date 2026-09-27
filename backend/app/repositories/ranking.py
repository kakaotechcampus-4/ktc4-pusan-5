from datetime import UTC, datetime

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ranking import RankingSnapshot
from app.schemas.base import CamelModel
from app.schemas.market_flow import SECTOR_KINDS


async def list_rankings(session: AsyncSession) -> dict[str, RankingSnapshot]:
    return {row.kind: row for row in (await session.scalars(select(RankingSnapshot))).all()}


async def save_ranking(
    session: AsyncSession,
    kind: str,
    items: list[CamelModel] | None,
    error: str | None,
    checked_at: datetime,
) -> None:
    values = {"kind": kind, "checked_at": checked_at, "error_code": error}
    if items is not None:
        values.update(
            items=[item.model_dump(mode="json") for item in items], collected_at=datetime.now(UTC)
        )
    statement = insert(RankingSnapshot).values(**values)
    updates = {key: value for key, value in values.items() if key != "kind"}
    if kind in SECTOR_KINDS and items:
        # ISO 날짜 비교를 UPSERT 내부에서 수행해 동시 저장 시에도 과거 값으로 돌아가지 않는다.
        old_date = RankingSnapshot.items[0]["as_of"].astext
        incoming_date = values["items"][0]["as_of"]
        outdated = old_date > incoming_date
        for key in ("items", "collected_at"):
            updates[key] = case(
                (outdated, getattr(RankingSnapshot, key)), else_=statement.excluded[key]
            )
        updates["error_code"] = case(
            (outdated, "OUTDATED_RESPONSE"), else_=statement.excluded.error_code
        )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["kind"],
            set_=updates,
        )
    )
