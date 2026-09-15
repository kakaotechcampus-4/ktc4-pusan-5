from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_or_create_user(
    session: AsyncSession,
    *,
    kakao_id: str,
    nickname: str,
    email: str,
) -> User:
    #kakao_id 로 조회
    #없으면 새로 만들고 / 있으면 정보 불러옴
    user = (
        await session.execute(select(User).where(User.kakao_id == kakao_id))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            kakao_id=kakao_id,
            nickname=nickname,
            email=email,
        )
        session.add(user)
    else:
        user.nickname = nickname
        user.email = email
        user.last_login_at = datetime.now(UTC)

    await session.flush()
    await session.refresh(user)
    return user


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)
