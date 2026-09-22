"""DB 엔진과 세션. 비동기 SQLAlchemy.

backend/app/core/database.py 와 같은 모양이지만 **다른 `Base` 다.** 여기 Base 는
`analyst_reports` 와 `stock_move_analysis*` 만 알고, backend Base 는 `news` 나
`report` 만 안다. 같은 Postgres 를 쓰지만 서로의 표를 모른다.

## 표는 alembic 이 만든다. 여기서 create_all 을 부르지 않는다

예전에는 이 파일에 `create_tables()` 가 있었고 수집 배치가 시작할 때 그걸 불렀다.
팀에서 alembic 을 쓰기로 정하면서 뺐다. 둘을 같이 두면 스키마를 만드는 길이 두
개가 되고, `create_all` 은 **이미 있는 표를 조용히 건너뛴다** — 칼럼이 하나 늘어난
모델로 create_all 을 불러도 기존 표는 그대로라, 코드는 새 칼럼을 쓰는데 DB 에는
없는 상태가 소리 없이 만들어진다. 그 상태로 alembic 을 돌리면 어디까지 적용됐는지
아무도 모른다.

    uv run alembic upgrade head     표 만들기·올리기
    uv run alembic revision --autogenerate -m "설명"   모델을 고친 뒤

**backend 는 아직 create_all 을 쓴다.** 그래도 충돌하지 않는다 — backend 의
create_all 은 자기 Base 만 보고, 여기 alembic 은 env.py 의 `include_object` 로
남의 표를 건드리지 않는다. backend 도 alembic 으로 옮기면 그때 이 주석을 지운다.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """테이블 모델의 부모"""
