import asyncio

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.models import User
from app.repositories.user import get_by_id, get_or_create_user


async def test_get_or_create_user_creates_then_updates_profile():
    async with SessionLocal() as session:
        created = await get_or_create_user(
            session,
            kakao_id="test-kakao-id-1",
            nickname="닉네임1",
            email="a@example.com",
        )
        assert created.id is not None
        assert created.nickname == "닉네임1"

        updated = await get_or_create_user(
            session,
            kakao_id="test-kakao-id-1",
            nickname="닉네임2",
            email="a@example.com",
        )
        assert updated.id == created.id
        assert updated.nickname == "닉네임2"

        fetched = await get_by_id(session, created.id)
        assert fetched is not None
        assert fetched.nickname == "닉네임2"

        await session.rollback()  # 커밋하지 않으므로 테스트 데이터는 남지 않는다


_CONCURRENT_KAKAO_ID = "test-concurrent-kakao-id"


async def _cleanup_concurrent_user() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.kakao_id == _CONCURRENT_KAKAO_ID))
        await session.commit()


async def test_get_or_create_user_handles_concurrent_calls_for_same_kakao_id():
    # 서로 다른 세션(=커넥션) 두 개가 같은 kakao_id로 동시에 upsert하는 상황.
    # 순차 SELECT-then-INSERT였다면 unique 제약 위반(IntegrityError)이 날 수 있음
    async def _call(nickname: str) -> User:
        async with SessionLocal() as session:
            user = await get_or_create_user(
                session,
                kakao_id=_CONCURRENT_KAKAO_ID,
                nickname=nickname,
                email="concurrent@example.com",
            )
            await session.commit()
            return user

    try:
        first, second = await asyncio.gather(_call("동시가입A"), _call("동시가입B"))
        assert first.id == second.id

        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(User).where(User.kakao_id == _CONCURRENT_KAKAO_ID)
                )
            ).scalars().all()
            assert len(rows) == 1
    finally:
        await _cleanup_concurrent_user()
