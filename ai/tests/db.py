"""실제 PostgreSQL 저장소 테스트 도우미. DB 는 tests/test_migrations.py 의 database 픽스처가 준다.

테스트 함수는 동기로 쓰고 여기서 asyncio.run 으로 돌린다. database 픽스처의 query() 가
asyncio.run 을 쓰므로 테스트를 async 로 쓰면 이벤트 루프 안에서 부를 수 없다.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def run_db(url: str, work: Callable[[async_sessionmaker], Awaitable[Any]]) -> Any:
    """테스트 DB 에 붙는 세션 팩토리를 work 에 넘겨 돌리고 결과를 돌려준다."""

    async def go() -> Any:
        engine = create_async_engine(url)
        try:
            return await work(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def in_session(url: str, work: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
    """세션 하나에서 work 를 돌리고 커밋한다."""

    async def wrapped(factory: async_sessionmaker) -> Any:
        async with factory() as session:
            result = await work(session)
            await session.commit()
            return result

    return run_db(url, wrapped)
