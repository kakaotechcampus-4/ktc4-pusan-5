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
# 여기 없는 표는 autogenerate 와 `alembic check` 이 아예 보지 않는다. 새 표를 만들면
# 반드시 추가해야 한다 — 빠뜨리면 마이그레이션이 없는데도 check 가 "변경 없음" 이라고 한다.
#
# news·source_card 는 backend 첫 리비전이 만든 표를 넘겨받은 것이다(0020·0022). backend 의
# migrations/env.py 는 이 둘을 비교에서 뺀다. 한 표를 두 쪽이 비교하면 서로 상대가 더한
# 칼럼을 지우라는 마이그레이션을 만든다.
MANAGED_TABLES = {
    "analyst_reports",
    "news",
    "source_card",
    "stock_move_analyses",
    "stock_move_analysis_factors",
    "stock_move_analysis_factor_sources",
    "stock_move_analysis_reviews",
    "telegram_messages",
    "telegram_message_links",
}
# backend 가 관리하는 표. FK 대상으로 모델에만 둔다. 비교·변경하지 않는다.
EXTERNAL_TABLES = {"channel"}


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """DB 에서 읽어 올 표를 고른다. backend 표는 아예 읽지 않는다."""
    if type_ == "table":
        return name in MANAGED_TABLES
    return True


def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    """모델 쪽 표를 고른다. include_name 은 DB 에서 읽은 이름에만 걸리므로, 모델에 FK 대상으로
    둔 EXTERNAL_TABLES 는 여기서 빼야 "새 표를 만들라" 로 잡히지 않는다."""
    if type_ == "table":
        return name in MANAGED_TABLES
    return True


def configure(**kwargs: Any) -> None:
    context.configure(
        **kwargs,
        target_metadata=target_metadata,
        version_table="alembic_version_ai",
        include_name=include_name,
        include_object=include_object,
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
