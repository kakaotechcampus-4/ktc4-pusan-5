from app.core.database import SessionLocal
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
