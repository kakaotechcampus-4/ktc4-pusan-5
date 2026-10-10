"""Real PostgreSQL checks for stock_move_analyses file-level idempotency.

같은 산출물 파일을 두 번 적재해도 행이 하나여야 하고, 재생성본(바이트가 다른 파일)은
지금처럼 새 행이어야 한다. MIGRATION_TEST_ADMIN_URL 이 없으면 skip 된다.
"""

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.stock_move_analysis import insert_analysis_files
from tests.test_migrations import alembic, query

FIXTURES = Path(__file__).parent / "fixtures" / "reports"
SAMSUNG = FIXTURES / "삼성전자-2026-09-18-with-indirect__B__r1.json"


def load(url, paths):
    """한 번의 배치. 새로 들어간 행 수를 돌려준다."""

    async def work():
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                inserted = await insert_analysis_files(session, paths)
                await session.commit()
                return len(inserted)
        finally:
            await engine.dispose()

    return asyncio.run(work())


def counts(url):
    analyses = query(url, "SELECT count(*) AS n FROM stock_move_analyses")[0]["n"]
    factors = query(url, "SELECT count(*) AS n FROM stock_move_analysis_factors")[0]["n"]
    sources = query(url, "SELECT count(*) AS n FROM stock_move_analysis_factor_sources")[0]["n"]
    return analyses, factors, sources


def test_same_file_loaded_twice_leaves_one_row(database):
    alembic(database, "upgrade", "head")

    assert load(database, [SAMSUNG]) == 1
    first = counts(database)
    assert first[0] == 1 and first[1] > 0 and first[2] > 0

    # 다른 배치에서 다시, 그리고 같은 배치 안에 두 번 — 둘 다 아무것도 넣지 않는다.
    assert load(database, [SAMSUNG]) == 0
    assert load(database, [SAMSUNG, SAMSUNG]) == 0
    assert counts(database) == first


def test_regenerated_file_is_still_a_new_row(database, tmp_path):
    """재생성본은 바이트가 달라 키가 다르다. 보고서 재생성은 막지 않는다."""
    alembic(database, "upgrade", "head")
    regenerated = tmp_path / SAMSUNG.name
    regenerated.write_bytes(SAMSUNG.read_bytes() + b"\n")

    assert load(database, [SAMSUNG]) == 1
    assert load(database, [regenerated]) == 1
    assert counts(database)[0] == 2


def test_report_sources_are_linked_to_source_cards_now_or_later(database, tmp_path):
    """출처 주소로 저장된 원문을 찾아 공통 자료 ID 를 잇는다. 못 찾은 출처는 나중에 다시 찾는다."""
    from app.repositories.source_card import register_missing_sources
    from app.repositories.stock_move_analysis import link_analysis_sources
    from tests.db import in_session

    alembic(database, "upgrade", "head")
    assert load(database, [SAMSUNG]) == 1
    linked = "SELECT count(*) FROM stock_move_analysis_factor_sources WHERE source_card_id IS NOT NULL"
    assert query(database, linked)[0][0] == 0, "원문이 아직 없다"

    # 보고서를 적재한 뒤에 그 메시지를 수집했다
    query(database, """
        INSERT INTO channel (telegram_handle, name, is_public, created_at)
        VALUES ('KISGregKim', 'KISGregKim', true, now())
    """)
    query(database, """
        INSERT INTO telegram_messages (channel_id, msg_id, url, posted_at, text, collected_via)
        SELECT id, 18692, 'https://t.me/KISGregKim/18692', '2026-09-18 09:00+09', '메시지', 'web'
        FROM channel
    """)
    in_session(database, register_missing_sources)
    wanted = query(database, "SELECT count(*) FROM stock_move_analysis_factor_sources "
                             "WHERE url = 'https://t.me/KISGregKim/18692'")[0][0]
    assert wanted > 0
    assert in_session(database, link_analysis_sources) == wanted
    assert query(database, linked)[0][0] == wanted
    assert in_session(database, link_analysis_sources) == 0, "이미 이은 출처는 다시 보지 않는다"

    # 원문이 이미 있으면 적재할 때 바로 잇는다 (재생성본은 새 행이다)
    regenerated = tmp_path / SAMSUNG.name
    regenerated.write_bytes(SAMSUNG.read_bytes() + b"\n")
    assert load(database, [regenerated]) == 1
    assert query(database, linked)[0][0] == wanted * 2
