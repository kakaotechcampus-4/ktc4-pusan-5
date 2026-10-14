"""dart_disclosures 저장·조회. 설계는 app/models/dart_disclosure.py 참고."""

from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DartDisclosure
from app.services.dart.schema import Disclosure


async def known_rcept_nos(session: AsyncSession, rcept_nos: list[str]) -> set[str]:
    """이미 저장된 접수번호."""
    if not rcept_nos:
        return set()
    rows = await session.execute(
        select(DartDisclosure.rcept_no).where(DartDisclosure.rcept_no.in_(rcept_nos))
    )
    return set(rows.scalars())


async def save_disclosures(session: AsyncSession, items: list[Disclosure]) -> int:
    """새 공시만 넣는다. 이미 있는 접수번호는 건드리지 않는다(first_seen_at 보존). 넣은 수."""
    if not items:
        return 0
    stmt = (
        insert(DartDisclosure)
        .values([asdict(item) for item in items])
        .on_conflict_do_nothing(constraint="uq_dart_disclosure_rcept_no")
        .returning(DartDisclosure.id)
    )
    return len((await session.execute(stmt)).all())
