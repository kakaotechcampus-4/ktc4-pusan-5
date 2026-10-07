"""수집 범위의 수집량(max_items)을 재는 쿼리. 범위 자체는 app/core/scope.py 가 읽는다."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalystReport, News, TelegramMessage

# 출처 → 그 경로로 쌓인 행. 보관 정책으로 본문을 지운 행도 센다.
COLLECTED = {
    "naver_news": (News, News.source == "naver"),
    "telegram_link": (News, News.source == "telegram"),
    "telegram_web": (TelegramMessage, TelegramMessage.collected_via == "web"),
    "telegram_client": (AnalystReport, AnalystReport.source == "telegram"),
    "naver_research": (AnalystReport, AnalystReport.source == "naver"),
}


async def count_collected(session: AsyncSession, source: str) -> int:
    """그 출처로 DB 에 쌓인 행 수. 같은 기사를 다른 경로로 다시 찾은 것은 처음 경로로 센다."""
    model, condition = COLLECTED[source]
    return (await session.execute(select(func.count()).select_from(model).where(condition))).scalar_one()
