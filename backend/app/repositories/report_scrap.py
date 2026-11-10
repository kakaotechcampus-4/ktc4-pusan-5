from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReportScrap


async def list_for_user(session: AsyncSession, user_id: int) -> list[ReportScrap]:
    result = await session.execute(
        select(ReportScrap)
        .where(ReportScrap.user_id == user_id)
        .order_by(ReportScrap.created_at.desc(), ReportScrap.id.desc())
    )
    return list(result.scalars().all())


# 이미 스크랩한 보고서면 무시
async def add(session: AsyncSession, user_id: int, report_id: int) -> None:
    await session.execute(
        pg_insert(ReportScrap)
        .values(user_id=user_id, report_id=report_id)
        .on_conflict_do_nothing(constraint="uq_report_scrap_user_report")
    )


async def remove(session: AsyncSession, user_id: int, report_id: int) -> None:
    await session.execute(
        delete(ReportScrap).where(
            ReportScrap.user_id == user_id, ReportScrap.report_id == report_id
        )
    )
