from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import News
from app.repositories.news import upsert_news

KST = timezone(timedelta(hours=9))


def _row(n: int) -> dict:
    return {
        "url": f"https://test.invalid/{n}",
        "title": f"t{n}",
        "publisher": "test.invalid",
        "source": "naver",
        "published_at": datetime(2026, 9, 12, 9, 30, tzinfo=KST),
        "summary": "",
        "cleaned_text": None,
    }


async def test_upsert_skips_duplicate_urls_and_keeps_timezone():
    async with SessionLocal() as session:
        assert await upsert_news(session, [_row(1), _row(2)]) == 2
        assert await upsert_news(session, [_row(1), _row(3)]) == 1  # 1은 중복

        stored = (
            await session.execute(select(News).where(News.url == "https://test.invalid/1"))
        ).scalar_one()
        assert stored.published_at.utcoffset() is not None
        assert stored.cleaned_text is None

        await session.rollback()  # 커밋하지 않으므로 테스트 데이터는 남지 않는다
