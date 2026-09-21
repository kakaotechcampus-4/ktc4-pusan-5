"""실제 PostgreSQL에서 신규 설치·기존 데이터 이전·공유 DB 격리를 검증한다.

MIGRATION_TEST_ADMIN_URL은 테스트 전용 PostgreSQL 접속 주소여야 한다.
테스트마다 pr18_migration_<uuid> DB를 만들고 해당 DB만 삭제한다.
앱의 DATABASE_URL이나 .env를 테스트 DB 선택에 사용하지 않는다.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

AI_DIR = Path(__file__).resolve().parents[1]
HEAD = "0018_source_category"


def alembic(url, *args, success=True):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=AI_DIR,
        env={**os.environ, "DATABASE_URL": url, "PYTHONIOENCODING": "utf-8"},
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def query(url, sql, *args):
    async def run():
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://", 1))
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return asyncio.run(run())


@pytest.fixture
def database():
    admin = os.environ.get("MIGRATION_TEST_ADMIN_URL")
    if not admin:
        pytest.skip("MIGRATION_TEST_ADMIN_URL is required for PostgreSQL migration tests")
    name = "pr18_migration_" + uuid4().hex
    query(admin, f'CREATE DATABASE "{name}"')
    url = make_url(admin).set(drivername="postgresql+asyncpg", database=name)
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        query(admin, f'DROP DATABASE "{name}" WITH (FORCE)')


def insert_old(url, source_id, category, end_url=None, source="naver"):
    query(
        url,
        """
        INSERT INTO analyst_reports
            (source, source_id, category, title, write_date, body_status, end_url, body_text)
        VALUES ($1, $2, $3, 'preserved title', '2026-09-18', 'ok', $4, 'preserved body')
    """,
        source,
        source_id,
        category,
        end_url,
    )


def test_offline_sql_and_single_head():
    url = "postgresql+asyncpg://unused:unused@localhost/unused"
    sql = alembic(url, "upgrade", "head", "--sql")
    assert "(?:api/)?research/" in sql
    assert "ADD COLUMN source_category" in sql
    assert "alembic_version_ai" in sql
    assert "CREATE TABLE analyst_reports" in sql
    assert alembic(url, "heads").strip() == f"{HEAD} (head)"


def test_fresh_database_matches_models_and_preserves_backend(database):
    query(database, "CREATE TABLE news (id integer PRIMARY KEY, content text)")
    query(database, "INSERT INTO news VALUES (1, 'backend data')")
    query(database, "CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
    query(database, "INSERT INTO alembic_version VALUES ('backend_revision')")
    alembic(database, "upgrade", "head")
    alembic(database, "upgrade", "head")
    alembic(database, "check")
    assert query(database, "SELECT content FROM news")[0][0] == "backend data"
    assert query(database, "SELECT version_num FROM alembic_version")[0][0] == "backend_revision"
    alembic(database, "downgrade", "base")
    assert query(database, "SELECT content FROM news")[0][0] == "backend data"
    alembic(database, "upgrade", "head")
    alembic(database, "check")


def test_legacy_data_backfill_and_upgrade_from_stamp(database):
    alembic(database, "upgrade", "0001")
    # Alembic 도입 이전 DB를 재현한다.
    query(database, "DROP TABLE alembic_version_ai")
    insert_old(database, "1", "company")
    insert_old(database, "2", "market", "https://m.stock.naver.com/research/invest/2")
    insert_old(database, "3", "market", "https://m.stock.naver.com/research/daily/3?foo=1")
    insert_old(database, "4", "market", "https://m.stock.naver.com/api/research/daily/4")
    alembic(database, "stamp", "0001")
    alembic(database, "upgrade", "head")
    rows = query(database, "SELECT source_category, body_text FROM analyst_reports ORDER BY id")
    assert [r[0] for r in rows] == ["company", "invest", "daily", "daily"]
    assert all(r[1] == "preserved body" for r in rows)
    alembic(database, "check")
    alembic(database, "downgrade", "0001")
    alembic(database, "upgrade", "head")
    assert len(query(database, "SELECT * FROM analyst_reports")) == 4


@pytest.mark.parametrize(
    "source,category,end_url",
    [
        ("naver", "market", None),
        ("naver", "market", "https://m.stock.naver.com/research/invest/999"),
        ("telegram", "company", None),
        ("naver", "market", "https://example.com/research/invest/1"),
    ],
)
def test_unrecoverable_rows_abort_without_changing_schema_or_data(
    database, source, category, end_url
):
    alembic(database, "upgrade", "0001")
    insert_old(database, "0", "company")
    insert_old(database, "1", category, end_url, source)
    before = query(database, "SELECT * FROM analyst_reports ORDER BY id")
    result = alembic(database, "upgrade", "head", success=False)
    assert "Cannot recover source_category" in result
    assert query(database, "SELECT * FROM analyst_reports ORDER BY id") == before
    assert query(database, "SELECT version_num FROM alembic_version_ai")[0][0] == "0001"
    assert not query(
        database,
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'analyst_reports' AND column_name = 'source_category'
    """,
    )


def test_new_natural_key_and_unsafe_downgrade(database):
    alembic(database, "upgrade", "head")
    for category in ["invest", "daily"]:
        query(
            database,
            """
            INSERT INTO analyst_reports
                (source, source_id, source_category, category, title, write_date, body_status)
            VALUES ('naver', '37550', $1, 'market', 'title', '2026-09-18', 'pending')
        """,
            category,
        )
    result = alembic(database, "downgrade", "0001", success=False)
    assert "Cannot restore the old natural key" in result
    assert len(query(database, "SELECT * FROM analyst_reports")) == 2
    assert query(database, "SELECT version_num FROM alembic_version_ai")[0][0] == HEAD
    alembic(database, "check")


def test_verified_current_schema_can_be_adopted_without_recreating_tables(database):
    from sqlalchemy.ext.asyncio import create_async_engine

    import app.models  # noqa: F401
    from app.core.database import Base

    async def create_legacy_schema():
        engine = create_async_engine(database)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(create_legacy_schema())
    query(
        database,
        """
        INSERT INTO analyst_reports
            (source, source_id, source_category, category, title, write_date, body_status)
        VALUES ('naver', '1', 'daily', 'market', 'preserve', '2026-09-18', 'pending')
    """,
    )
    # 현재 모델로 만든 DB이므로 구조가 일치한다. 실제 기존 DB는 별도 확인이 필요하다.
    alembic(database, "stamp", HEAD)
    alembic(database, "upgrade", "head")
    alembic(database, "check")
    assert query(database, "SELECT title FROM analyst_reports")[0][0] == "preserve"
