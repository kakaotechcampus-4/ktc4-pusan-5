"""DB 엔진과 세션. 비동기 SQLAlchemy."""

from collections.abc import AsyncIterator
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class SchemaOutdatedError(RuntimeError):
    """DB 리비전이 코드의 alembic head 와 다름"""


async def ensure_schema_current() -> None:
    """스키마를 바꾸지 않고, DB 가 alembic head 까지 올라와 있는지만 확인."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    heads = set(ScriptDirectory.from_config(config).get_heads())
    async with engine.connect() as connection:
        current = set(
            await connection.run_sync(
                lambda sync: MigrationContext.configure(sync).get_current_heads()
            )
        )
    if current != heads:
        raise SchemaOutdatedError(
            f"DB schema {sorted(current) or 'empty'} != alembic head {sorted(heads)}. "
            "`uv run alembic upgrade head` 를 실행하여 alembic head를 맞추어야 함"
        )


class Base(DeclarativeBase):
    """테이블 모델의 부모"""


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
