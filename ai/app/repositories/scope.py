"""수집 범위의 수집량(max_items)을 재는 쿼리. 범위 자체는 app/core/scope.py 가 읽는다."""

from contextlib import asynccontextmanager

from sqlalchemy import func, select, text
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


@asynccontextmanager
async def collection_locks(session_factory, *sources: str):
    """출처별 수집을 직렬화해 수량 확인과 저장 사이의 상한 초과를 막는다.

    원문 저장과 별도 트랜잭션으로 잠금을 유지한다. 수집기가 묶음마다 커밋해도 풀리지
    않으며, 예외·취소·연결 종료 시 트랜잭션과 함께 해제된다. 여러 출처는 이름순으로 잠근다.
    네트워크 수집 동안 연결 하나를 사용하므로 실행당 작업 세션과 잠금 세션이 필요하다.
    """
    async with session_factory() as session:
        for source in sorted(set(sources)):
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"collection:{source}"},
            )
        yield


async def count_collected(session: AsyncSession, source: str) -> int:
    """그 출처로 DB 에 쌓인 행 수. 같은 기사를 다른 경로로 다시 찾은 것은 처음 경로로 센다."""
    model, condition = COLLECTED[source]
    return (await session.execute(select(func.count()).select_from(model).where(condition))).scalar_one()
