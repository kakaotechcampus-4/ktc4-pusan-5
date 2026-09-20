"""Alembic environment for the explicitly managed stock schema."""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.schema import MetaData

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.models import stock as stock_models
from app.models import stock_financials  # noqa: F401 — register financial tables on Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = MetaData()
MANAGED_TABLES = {
    "stock",
    "stock_quote_snapshot",
    "stock_metric_snapshot",
    "stock_daily_price",
    "stock_collection_state",
    "stock_collection_job",
    "stock_data_coverage",
    "stock_annual_income",
    "stock_annual_eps",
}
for table in stock_models.Base.metadata.sorted_tables:
    if table.name in MANAGED_TABLES:
        table.to_metadata(target_metadata)


def include_name(name, type_, parent_names) -> bool:
    """Keep autogenerate reflection limited to the stock migration scope."""

    if type_ == "table":
        return name in MANAGED_TABLES
    parent_table = parent_names.get("table_name")
    return parent_table is None or parent_table in MANAGED_TABLES


def get_url() -> str:
    """Read the database URL through application settings without logging it."""

    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
