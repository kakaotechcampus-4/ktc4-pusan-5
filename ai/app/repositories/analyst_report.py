from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalystReport


async def known_ids(session: AsyncSession, source: str, category: str, since: date) -> set[str]:
    """since 이후로 이미 받아둔 리포트 ID.

    목록은 한 번에 100건씩 오지만 상세·PDF 는 건당 2회 호출이다. 이미 있는 걸 먼저
    걸러내지 않으면 매일 같은 리포트를 수백 번 다시 받는다. 증분 수집의 핵심이다.
    """
    rows = await session.execute(
        select(AnalystReport.source_id).where(
            AnalystReport.source == source,
            AnalystReport.category == category,
            AnalystReport.write_date >= since,
        )
    )
    return set(rows.scalars().all())


async def upsert_analyst_reports(session: AsyncSession, rows: list[dict]) -> int:
    """(source, category, source_id) 가 자연키다. 같은 기간을 다시 돌려도 중복이 안 생긴다.

    뉴스(`upsert_news`)는 URL 이 같으면 통째로 건너뛰지만 리포트는 갱신한다 —
    읽은 수와 요약이 나중에 바뀌는 일이 있다. 다만 **본문 추출에 성공한 행을
    pending 으로 덮어쓰지는 않는다**(아래 where). PDF 를 못 받은 재실행이
    이미 뽑아둔 본문을 지우면 안 되기 때문이다.

    돌려주는 값은 '보낸 행 수'다. rowcount 가 아니다 — ON CONFLICT DO UPDATE 는
    새로 넣은 것과 갱신한 것을 구분해주지 않는다.
    """
    if not rows:
        return 0
    stmt = insert(AnalystReport).values(rows)
    updatable = [c for c in rows[0] if c not in ("source", "category", "source_id")]
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_analyst_report_source_id",
            set_={c: getattr(stmt.excluded, c) for c in updatable},
            where=stmt.excluded.body_status != "pending",
        )
    )
    return len(rows)
