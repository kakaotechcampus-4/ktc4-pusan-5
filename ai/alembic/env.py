"""Alembic 실행 환경.

이 Base 는 `ai/` 의 표만 안다(analyst_reports, stock_move_report*). backend 의
`news` 나 `report` 는 여기 metadata 에 없다. 그래서 **autogenerate 가 backend 표를
"모델에 없는 표" 로 보고 drop 하려 든다.** `include_object` 가 그걸 막는다 —
같은 Postgres 를 쓰는 두 프로젝트가 각자 마이그레이션을 돌려도 서로를 안 건드린다.

접속 정보는 alembic.ini 가 아니라 app.core.config.settings 에서 읽는다. 비밀키는
환경변수로만 읽는다는 규칙이 앱과 마이그레이션 양쪽에 똑같이 걸려야 한다.

**alembic.ini 는 영어로만 쓴다.** alembic 이 그 파일을 UTF-8 이 아니라 **로캘
인코딩**으로 읽어서, 한국어 Windows(cp949)에서 한글 주석이 있으면
UnicodeDecodeError 로 죽는다. 설명이 필요하면 여기(.py 는 UTF-8 로 읽힌다)나
README 에 적는다.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# app.models 는 쓰지 않는데도 import 한다. 이게 있어야 모델이 Base.metadata 에
# 등록되고, autogenerate 가 표를 본다. 빠지면 "표가 하나도 없다" 는 마이그레이션이
# 생성된다 — 즉 기존 표를 전부 DROP 하는 리비전이 나온다.
import app.models  # noqa: F401
from alembic import context
from app.core.config import settings
from app.core.database import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    # disable_existing_loggers 기본값이 True 다. 그대로 두면 alembic 을 부르는 순간
    # app.* 로거가 전부 꺼져서, 같은 프로세스에서 도는 적재 로그가 사라진다.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """이 프로젝트의 metadata 에 없는 표는 autogenerate 대상에서 뺀다.

    backend 가 같은 DB 에 만든 표(news, report, source_card …)를 여기서 보면
    "모델에 없으니 지워라" 가 되어 남의 표에 DROP 이 찍힌다. 반대로 backend 가
    alembic 을 쓰게 되면 그쪽도 같은 장치가 필요하다.
    """
    return not (type_ == "table" and reflected and name not in target_metadata.tables)


def run_migrations_offline() -> None:
    """DB 에 붙지 않고 SQL 만 찍는다(`alembic upgrade head --sql`).

    운영 DB 에 무엇이 나갈지 사람이 먼저 읽어 보는 용도이고, 테스트에서도 이 경로로
    마이그레이션과 모델이 어긋나지 않았는지 확인한다 — DB 없이 돌려야 하기 때문이다.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        # 칼럼 타입 변경을 autogenerate 가 잡게 한다. 기본값은 꺼져 있어서
        # String(16) → String(32) 같은 변경이 조용히 누락된다.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
