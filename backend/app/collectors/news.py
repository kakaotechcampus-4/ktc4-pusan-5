"""뉴스 수집 → 정규화 → DB 저장.

uv run python -m app.collectors.news 삼성전자
uv run python -m app.collectors.news 삼성전자 --display 50
"""

import argparse
import asyncio

from app.core.database import SessionLocal
from app.repositories.news import upsert_news
from app.services.news import naver
from app.services.news.content import attach_bodies
from app.services.news.schema import NewsItem


def _to_row(item: NewsItem) -> dict:
    return {
        "url": str(item.url),
        "title": item.title,
        "publisher": item.publisher,
        "source": item.source,
        "published_at": item.published_at,
        "summary": item.summary,
        "cleaned_text": item.cleaned_text,
    }


async def collect(query: str, *, display: int = 20) -> tuple[int, int]:
    """(가져온 건수, 새로 저장된 건수)"""
    items = await naver.search(query, display=display)
    items = await attach_bodies(items)
    # 여기가 나중에 skills/ 분석이 들어갈 자리

    async with SessionLocal() as session:
        inserted = await upsert_news(session, [_to_row(i) for i in items])
        await session.commit()
    return len(items), inserted


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("query")
    p.add_argument("--display", type=int, default=20)
    args = p.parse_args()
    fetched, inserted = asyncio.run(collect(args.query, display=args.display))
    print(f"가져온 {fetched}건 / 새로 저장 {inserted}건")


if __name__ == "__main__":
    main()
