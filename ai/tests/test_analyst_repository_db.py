"""Real PostgreSQL checks for natural keys and existing report preservation."""

import asyncio
from datetime import date

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.repositories.analyst_report import known_ids, upsert_analyst_reports
from tests.test_migrations import alembic, query


def report(source="telegram", category="channel_one", source_id="1", **values):
    return {
        "source": source,
        "source_category": category,
        "source_id": source_id,
        "category": "market",
        "title": "title",
        "write_date": date(2020, 1, 1),
        "summary_text": "reviewed summary",
        "summary_chars": 16,
        "body_status": "ok",
        "body_text": "original body",
        "body_chars": 13,
        "pdf_sha256": "a" * 64,
        "attach_url": "https://example.com/original.pdf",
        **values,
    }


def save(url, rows):
    async def work():
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine)() as session:
                await upsert_analyst_reports(session, rows)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(work())


def test_same_message_number_in_two_channels_and_recollection_preserve_rows(database):
    alembic(database, "upgrade", "head")
    save(database, [report(), report(category="channel_two")])
    before = query(database, "SELECT * FROM analyst_reports ORDER BY id")
    save(
        database,
        [
            report(
                title="changed",
                summary_text=None,
                summary_chars=None,
                body_status="failed",
                body_text=None,
                pdf_sha256=None,
            )
        ],
    )
    assert query(database, "SELECT * FROM analyst_reports ORDER BY id") == before


def test_old_report_posted_today_is_already_known(database):
    alembic(database, "upgrade", "head")
    save(database, [report()])

    async def work():
        engine = create_async_engine(database)
        try:
            async with async_sessionmaker(engine)() as session:
                return await known_ids(session, "telegram", date(2026, 9, 22), "channel_one")
        finally:
            await engine.dispose()

    assert asyncio.run(work()) == {"1"}


def test_naver_market_keeps_original_identity_and_failed_pdf_does_not_erase_body(database):
    alembic(database, "upgrade", "head")
    save(database, [report("naver", "invest"), report("naver", "daily")])
    save(
        database,
        [
            report(
                "naver",
                "invest",
                body_status="failed",
                body_text=None,
                body_chars=None,
                pdf_sha256=None,
                summary_text="new API summary",
                attach_url="https://example.com/unavailable.pdf",
            )
        ],
    )
    rows = query(database, "SELECT * FROM analyst_reports ORDER BY id")
    assert len(rows) == 2
    assert all(r["category"] == "market" for r in rows)
    assert rows[0]["summary_text"] == "new API summary"
    assert rows[0]["body_text"] == "original body"
    assert rows[0]["body_status"] == "ok"
    assert rows[0]["pdf_sha256"] == "a" * 64
    assert rows[0]["attach_url"] == "https://example.com/original.pdf"


def test_telegram_pdf_already_in_naver_is_not_saved(database):
    alembic(database, "upgrade", "head")
    save(database, [report("naver", "company")])
    before = query(database, "SELECT * FROM analyst_reports ORDER BY id")
    save(database, [report(title="다른 파일명이어도 같은 PDF")])
    assert query(database, "SELECT * FROM analyst_reports ORDER BY id") == before


def test_same_title_different_pdf_and_missing_hash_are_not_discarded(database):
    alembic(database, "upgrade", "head")
    save(database, [report("naver", "company")])
    save(database, [report(pdf_sha256="b" * 64), report(source_id="2", pdf_sha256=None)])
    assert len(query(database, "SELECT * FROM analyst_reports")) == 3


def test_naver_wins_same_pdf_in_a_mixed_batch(database):
    alembic(database, "upgrade", "head")
    save(database, [report(), report("naver", "company")])
    assert [r[0] for r in query(database, "SELECT source FROM analyst_reports")] == ["naver"]


def test_telegram_waits_for_inflight_naver_insert(database):
    alembic(database, "upgrade", "head")
    async def work():
        engine = create_async_engine(database)
        try:
            sessions = async_sessionmaker(engine)
            async with sessions() as naver, sessions() as telegram:
                await upsert_analyst_reports(naver, [report("naver", "company")])
                task = asyncio.create_task(upsert_analyst_reports(telegram, [report()]))
                await asyncio.sleep(0.05)
                await naver.commit()
                assert await asyncio.wait_for(task, timeout=5) == 0
                await telegram.commit()
        finally:
            await engine.dispose()
    asyncio.run(work())
    assert [r[0] for r in query(database, "SELECT source FROM analyst_reports")] == ["naver"]
