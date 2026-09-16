"""DB 엔진과 세션. 비동기 SQLAlchemy.

backend/app/core/database.py 와 같은 모양이지만 **다른 `Base` 다.** 여기 Base 는
`analyst_reports` 만 알고, backend Base 는 `news` 만 안다. 각자 `create_all` 을
불러도 자기 표만 만들기 때문에 같은 DB 를 써도 서로를 건드리지 않는다.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """테이블 모델의 부모"""


async def create_tables() -> None:
    """이 패키지가 쓰는 표를 만든다. 이미 있으면 아무 일도 안 한다.

    backend 는 FastAPI lifespan 에서 이걸 한다. 여기는 서버가 없으므로
    수집 배치를 시작할 때 부른다. alembic 을 쓰지 않는 건 팀 backend 를 따른 것이다 —
    마이그레이션 도구가 프로젝트마다 다르면 스키마 변경 절차가 두 개가 된다.
    """
    import app.models  # noqa: F401  — 모델을 import 해야 Base.metadata 에 등록된다

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
