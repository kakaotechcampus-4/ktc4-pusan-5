"""AI 스키마만 비교하고, backend와 별도의 테이블에 적용 이력을 저장한다."""

import asyncio
from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401 — 모델 등록
from alembic import context
from app.core.config import settings
from app.core.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
# 모델에서 제거한 테이블도 삭제 대상으로 검출하도록 소유 목록을 별도로 둔다.
MANAGED_TABLES = {"analyst_reports"}


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    if type_ == "table":
        return name in MANAGED_TABLES
    return True


def configure(**kwargs: Any) -> None:
    context.configure(
        **kwargs,
        target_metadata=target_metadata,
        version_table="alembic_version_ai",
        include_name=include_name,
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    configure(
        url=settings.database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # URL을 ConfigParser에 넣지 않는다. 비밀번호의 %도 그대로 처리한다.
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
