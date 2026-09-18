from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_or_create_user(
    session: AsyncSession,
    *,
    kakao_id: str,
    nickname: str,
    email: str,
) -> User:
    # kakao_id 로 atomic upsert.
    # INSERT ... ON CONFLICT (kakao_id) DO UPDATE ... RETURNING
    stmt = (
        pg_insert(User)
        .values(kakao_id=kakao_id, nickname=nickname, email=email)
        .on_conflict_do_update(
            index_elements=[User.kakao_id],
            set_={
                "nickname": nickname,
                "email": email,
                "last_login_at": func.now(),
            },
        )
        .returning(User)
    )
    # RETURNING으로 받은 최신 값으로 덮어씌움
    result = await session.execute(stmt, execution_options={"populate_existing": True})
    user = result.scalar_one()
    await session.flush()
    return user


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)
