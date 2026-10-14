"""실제 PostgreSQL에서 신규 설치·기존 데이터 이전·공유 DB 격리를 검증한다.

MIGRATION_TEST_ADMIN_URL은 테스트 전용 PostgreSQL 접속 주소여야 한다.
테스트마다 pr18_migration_<uuid> DB를 만들고 해당 DB만 삭제한다.
앱의 DATABASE_URL이나 .env를 테스트 DB 선택에 사용하지 않는다.

`database` 는 실제 설치 순서대로 backend 첫 리비전의 표(news·channel·source_card 등)를 먼저
만든 DB 다(tests/backend_schema.py). AI 는 그 표를 넘겨받거나 FK 로 가리키므로, 그 표가 없으면
0020 부터 중단한다. 아무 표도 없는 DB 가 필요하면 `empty_database` 를 쓴다.
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

from tests.backend_schema import BACKEND_HEAD, backend_statements

AI_DIR = Path(__file__).resolve().parents[1]
# 체인 끝이 바뀌면 여기도 바꾼다. stamp·버전 확인이 전부 이 값을 쓴다.
HEAD = "0023_analyst_report_purge"
# AI 가 backend 에게서 넘겨받기 직전 리비전
BEFORE_TAKEOVER = "0019_stock_move_analysis"


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
def empty_database():
    """아무 표도 없는 테스트 DB."""
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


@pytest.fixture
def database(empty_database):
    """backend 가 먼저 `alembic upgrade head` 를 마친 DB. 실제 설치 순서와 같다."""
    for statement in backend_statements():
        query(empty_database, statement)
    return empty_database


def columns(url, table):
    return {
        row["column_name"]: row["is_nullable"] == "YES"
        for row in query(
            url,
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = $1",
            table,
        )
    }


def insert_legacy_news(url, n, cleaned_text):
    """backend 가 수집해 둔 기사. backend 첫 리비전의 칼럼만 있다."""
    query(
        url,
        """
        INSERT INTO news (id, url, title, publisher, source, published_at, summary, cleaned_text,
                          collected_at)
        VALUES ($1, $2, $3, 'example.com', 'naver', '2026-09-30 09:00+09', 'summary', $4,
                '2026-09-30 10:00+09')
    """,
        n,
        f"https://example.com/news/{n}?utm_source=naver",
        f"legacy {n}",
        cleaned_text,
    )


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
    # backend 표는 만들지 않고 고치기만 한다
    assert "CREATE TABLE news" not in sql
    assert "CREATE TABLE source_card" not in sql
    assert "ALTER TABLE news ADD COLUMN body_status" in sql
    assert "CREATE TABLE telegram_messages" in sql
    assert "ALTER TABLE source_card ADD COLUMN news_id" in sql
    assert "ALTER TABLE analyst_reports ADD COLUMN purged_at" in sql
    assert alembic(url, "heads").strip() == f"{HEAD} (head)"


def test_fresh_database_matches_models_and_preserves_backend(database):
    query(database, "INSERT INTO channel (telegram_handle, name, is_public, created_at) "
                    "VALUES ('reviewed', 'backend channel', true, now())")
    alembic(database, "upgrade", "head")
    alembic(database, "upgrade", "head")
    alembic(database, "check")
    # backend 의 이력·데이터는 그대로다
    assert query(database, "SELECT version_num FROM alembic_version")[0][0] == BACKEND_HEAD
    assert query(database, "SELECT name FROM channel")[0][0] == "backend channel"
    alembic(database, "downgrade", "base")
    # 넘겨받은 표는 backend 첫 리비전 모양으로 돌아가고 지워지지 않는다
    assert set(columns(database, "news")) == {
        "id", "url", "title", "publisher", "source", "published_at", "summary", "cleaned_text",
        "collected_at",
    }
    assert columns(database, "news")["published_at"] is False
    assert "news_id" not in columns(database, "source_card")
    assert not columns(database, "telegram_messages")
    assert query(database, "SELECT version_num FROM alembic_version")[0][0] == BACKEND_HEAD
    alembic(database, "upgrade", "head")
    alembic(database, "check")


def test_empty_database_needs_backend_tables_first(empty_database):
    """news 를 AI 가 만들면 나중에 backend 첫 리비전이 같은 표를 만들다 실패한다."""
    result = alembic(empty_database, "upgrade", "head", success=False)
    assert "news table is missing" in result
    # 한 트랜잭션이라 앞 리비전까지 전부 되돌아간다. 반쯤 올라간 DB 가 남지 않는다.
    assert not columns(empty_database, "analyst_reports")
    for statement in backend_statements():
        query(empty_database, statement)
    alembic(empty_database, "upgrade", "head")
    alembic(empty_database, "check")


def test_news_takeover_keeps_rows_and_ids_and_backfills_body_state(database):
    insert_legacy_news(database, 7, "본문이 있는 기사")
    insert_legacy_news(database, 8, None)  # backend 가 본문 추출에 실패한 기사
    insert_legacy_news(database, 9, "")
    before = query(database, "SELECT * FROM news ORDER BY id")
    alembic(database, "upgrade", "head")
    alembic(database, "check")

    rows = query(database, "SELECT * FROM news ORDER BY id")
    for old, new in zip(before, rows, strict=True):
        assert {k: new[k] for k in dict(old)} == dict(old), "기존 칼럼 값은 그대로다"
    assert [(r["id"], r["body_status"], r["body_error"], r["body_extractor"]) for r in rows] == [
        (7, "ok", None, "trafilatura"),
        (8, "failed", "unrecorded", None),
        (9, "failed", "unrecorded", None),
    ]
    assert all(r["body_fetched_at"] == r["collected_at"] for r in rows)
    # 정규화 주소는 등록 처리가 채운다. 리비전이 앱 코드의 규칙을 쓰지 않는다
    assert all(r["canonical_url"] is None for r in rows)
    assert columns(database, "news")["published_at"] is True


def test_news_downgrade_refuses_rows_without_publish_time(database):
    alembic(database, "upgrade", "head")
    query(database, """
        INSERT INTO news (url, title, publisher, source, published_at, summary, body_status)
        VALUES ('https://example.com/a', '', 'example.com', 'telegram', NULL, '', 'failed')
    """)
    result = alembic(database, "downgrade", BEFORE_TAKEOVER, success=False)
    assert "Cannot restore NOT NULL on news.published_at: 1 row(s)" in result
    assert query(database, "SELECT version_num FROM alembic_version_ai")[0][0] == HEAD
    assert len(query(database, "SELECT * FROM news")) == 1


def test_retention_purge_records_block_downgrade(database):
    """지운 기록을 잃으면 예전 코드의 재수집이 본문을 되살린다. 그래서 되돌리지 않는다."""
    alembic(database, "upgrade", "head")
    query(database, """
        INSERT INTO analyst_reports (source, source_category, source_id, category, title,
                                     write_date, body_status, purged_at, purge_reason)
        VALUES ('naver', 'company', '1', 'company', 't', '2026-10-01', 'purged', now(), '정책')
    """)
    result = alembic(database, "downgrade", "0022_source_card_sources", success=False)
    assert "Cannot drop analyst_reports purge records: 1 row(s)" in result

    query(database, "DELETE FROM analyst_reports")
    query(database, """
        INSERT INTO news (url, title, publisher, source, published_at, summary, body_status,
                          purged_at, purge_reason)
        VALUES ('https://example.com/1', 't', 'example.com', 'naver', now(), '', 'purged',
                now(), '정책')
    """)
    result = alembic(database, "downgrade", BEFORE_TAKEOVER, success=False)
    assert "Cannot drop news purge records: 1 row(s)" in result
    assert query(database, "SELECT version_num FROM alembic_version_ai")[0][0] == HEAD


def test_source_card_takeover_refuses_existing_cards_of_raw_types(database):
    query(database, """
        INSERT INTO source_card (card_type, tags, payload, created_at)
        VALUES ('news', '[]', '{}', now())
    """)
    before = query(database, "SELECT * FROM source_card")
    result = alembic(database, "upgrade", "head", success=False)
    assert "Cannot link source_card to raw sources: 1 existing card(s)" in result
    assert query(database, "SELECT * FROM source_card") == before
    assert "news_id" not in columns(database, "source_card")


def test_source_card_downgrade_refuses_while_cards_point_to_raw_rows(database):
    alembic(database, "upgrade", "head")
    query(database, """
        INSERT INTO news (id, url, title, publisher, source, published_at, summary, cleaned_text,
                          body_status)
        VALUES (1, 'https://example.com/1', 't', 'example.com', 'naver', now(), '', '본문', 'ok')
    """)
    query(database, """
        INSERT INTO source_card (card_type, news_id, tags, payload, created_at)
        VALUES ('news', 1, '[]', '{}', now())
    """)
    result = alembic(database, "downgrade", "0021_telegram_messages", success=False)
    assert "Cannot unlink source_card: 1 card(s)" in result
    assert query(database, "SELECT news_id FROM source_card")[0][0] == 1


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
    assert "Cannot recover source_category: 1 row(s). Sample report IDs: {2}" in result
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


def test_verified_current_schema_can_be_adopted_without_recreating_tables(empty_database):
    # 현재 모델의 create_all 이 만든 DB 다. backend 표가 미리 있으면 create_all 이 그 표를
    # 건너뛰어 backend 첫 리비전 모양으로 남으므로, 빈 DB 에서 모델 그대로 만든다.
    from sqlalchemy.ext.asyncio import create_async_engine

    import app.models  # noqa: F401
    from app.core.database import Base

    database = empty_database

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


def test_failure_summary_and_full_diagnostic_query_after_rollback(database):
    alembic(database, "upgrade", "0001")
    insert_old(database, "valid", "company")
    insert_old(database, "8", "market", "https://m.stock.naver.com/research/daily/8")
    for i in range(7):
        insert_old(database, str(i), "market")
    before = query(database, "SELECT * FROM analyst_reports ORDER BY id")
    result = alembic(database, "upgrade", "head", success=False)
    assert "Cannot recover source_category: 7 row(s). Sample report IDs: {3,4,5,6,7}" in result
    assert query(database, "SELECT * FROM analyst_reports ORDER BY id") == before
    # README에 제공한 SQL 자체를 실행해 롤백 후 전체 실패 행을 찾는지 확인한다.
    readme = (AI_DIR / "README.md").read_text(encoding="utf-8")
    diagnostic_sql = readme.split("```sql\n", 1)[1].split("```", 1)[0]
    assert [row["id"] for row in query(database, diagnostic_sql)] == list(range(3, 10))
