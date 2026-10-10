"""수집 재실행과 동시성 회귀 검사. 외부 API 없이 실제 PostgreSQL에서 실행한다."""

import asyncio
from datetime import timedelta

import httpx
from sqlalchemy import text

from app.collectors import news as news_collector
from app.collectors.news_channels import run, save_to_db
from app.models import News
from app.repositories.news import save_news
from app.repositories.retention import PurgeTargets, purge
from app.repositories.source_card import (
    backfill_canonical_urls,
    get_sources,
    register_missing_sources,
)
from app.services.news_link.schema import LinkBody
from app.services.telegram_web import ChannelMessage
from tests.db import in_session, run_db
from tests.test_migrations import alembic, query
from tests.test_news_channels import ARTICLE_HTML as MOCK_ARTICLE_HTML
from tests.test_news_collector import _item as mock_item
from tests.test_news_collector import _scope as mock_news_scope
from tests.test_news_repository_db import failed as mock_failed
from tests.test_news_repository_db import row as mock_news
from tests.test_telegram_message_repository_db import NOW, SKITTEAM, channel_scope
from tests.test_telegram_web import box, page


async def wait_for_blocked_query(factory):
    """경쟁 작업이 실제 DB 잠금을 기다릴 때까지 기다린다. 고정 지연으로 순서를 추측하지 않는다."""
    async with asyncio.timeout(8), factory() as session:
        while True:
            blocked = await session.scalar(text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND cardinality(pg_blocking_pids(pid)) > 0"
            ))
            await session.commit()  # pg_stat_activity 스냅샷을 갱신하여 새 연결도 관찰한다.
            if blocked:
                return
            await asyncio.sleep(0.01)


def test_purge_wins_over_concurrent_fetch_and_stale_identity_map(database):
    alembic(database, "upgrade", "head")
    [mock_id] = in_session(database, lambda s: save_news(s, [mock_failed()])).ids

    async def work(factory):
        async def collect_again():
            async with factory() as session:
                result = await save_news(session, [mock_news()])
                await session.commit()
                return result

        async with factory() as cached, factory() as deleting:
            stale = await cached.get(News, mock_id)
            await purge(deleting, PurgeTargets(news=[mock_id]), reason="mock retention")
            fetching = asyncio.create_task(collect_again())
            try:
                await wait_for_blocked_query(factory)
            finally:
                await deleting.commit()
            assert (await asyncio.wait_for(fetching, 8)).filled == 0
            assert stale.body_status == "failed"
            assert (await save_news(cached, [mock_news()])).filled == 0
            await cached.commit()
            assert stale.body_status == "purged"

    run_db(database, work)
    [stored] = query(database, "SELECT body_status, cleaned_text, purged_at FROM news")
    assert stored["body_status"] == "purged" and stored["cleaned_text"] is None
    assert stored["purged_at"] is not None


def test_backfill_and_collection_do_not_deadlock_when_id_and_url_order_differ(database):
    alembic(database, "upgrade", "head")
    in_session(database, lambda s: save_news(s, [
        mock_failed("https://example.com/z"), mock_failed("https://example.com/a"),
    ]))
    query(database, "UPDATE news SET canonical_url = NULL")

    async def work(factory):
        first_lock = asyncio.Event()
        release = asyncio.Event()

        async def backfill():
            async with factory() as session:
                execute = session.execute

                async def mock_execute(stmt, *args, **kwargs):
                    result = await execute(stmt, *args, **kwargs)
                    if "pg_advisory_xact_lock" in str(stmt) and not first_lock.is_set():
                        first_lock.set()
                        await release.wait()
                    return result

                session.execute = mock_execute
                await backfill_canonical_urls(session)
                await session.commit()

        async def collect_again():
            async with factory() as session:
                await save_news(session, [
                    mock_news("https://example.com/a"), mock_news("https://example.com/z"),
                ])
                await session.commit()

        filling = asyncio.create_task(backfill())
        await asyncio.wait_for(first_lock.wait(), 8)
        collecting = asyncio.create_task(collect_again())
        try:
            await wait_for_blocked_query(factory)
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(filling, collecting), 8)

    run_db(database, work)
    assert [r[0] for r in query(database, "SELECT body_status FROM news")] == ["ok", "ok"]


def test_parallel_news_collections_respect_the_shared_quota(database, monkeypatch):
    alembic(database, "upgrade", "head")

    async def work(factory):
        first_fetch = asyncio.Event()
        release = asyncio.Event()
        mock_search_count = 0

        async def mock_search(*args, **kwargs):
            nonlocal mock_search_count
            mock_search_count += 1
            return [mock_item(url=f"https://example.com/{mock_search_count}")]

        async def mock_attach(items):
            if items:
                first_fetch.set()
                await release.wait()
            return items

        monkeypatch.setattr(news_collector, "SessionLocal", factory)
        monkeypatch.setattr(news_collector.naver, "search", mock_search)
        monkeypatch.setattr(news_collector, "attach_bodies", mock_attach)
        mock_scope = mock_news_scope(max_items=1)
        mock_query = next(iter(mock_scope.require("naver_news").allowed))
        first = asyncio.create_task(news_collector.collect(mock_query, scope=mock_scope))
        await asyncio.wait_for(first_fetch.wait(), 8)
        second = asyncio.create_task(news_collector.collect(mock_query, scope=mock_scope))
        try:
            await wait_for_blocked_query(factory)
        finally:
            release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 8)
        assert sum(r.inserted for r in results) == 1
        assert sum(r.held for r in results) == 1

    run_db(database, work)
    assert query(database, "SELECT count(*) FROM news")[0][0] == 1


def test_href_only_edit_never_combines_old_discovery_with_new_target(database):
    alembic(database, "upgrade", "head")

    def collect_link(url, status):
        mock_body = LinkBody(url=url, final_url=url, fetched_at=NOW, domain="example.com",
                             status=status, text="mock article" if status == "ok" else None)
        mock_message = ChannelMessage(
            channel=SKITTEAM.id, msg_id=1, url="https://t.me/skitteam/1", posted_at=NOW,
            text="unchanged anchor text", links=[url], link_bodies=[mock_body],
        )
        return run_db(database, lambda factory: save_to_db(
            [mock_message], (SKITTEAM,), now=NOW, per_message=3, session_factory=factory,
        ))

    collect_link("https://example.com/old", "http_error")
    collect_link("https://example.com/new", "ok")
    [stored] = query(database, """
        SELECT l.discovered_url, l.final_url, n.url, l.status
        FROM telegram_message_links l JOIN news n ON n.id = l.news_id
    """)
    assert tuple(stored) == ("https://example.com/old", "https://example.com/old",
                             "https://example.com/old", "http_error")


def test_failed_article_retries_at_quota_and_success_is_reused(database):
    alembic(database, "upgrade", "head")
    mock_opened = []
    mock_status = 503

    def mock_handler(request):
        if request.url.host == "t.me":
            if request.url.params.get("before"):
                return httpx.Response(200, html=page())
            return httpx.Response(200, html=page(
                box("skitteam/1", time="2026-10-05T02:00:00+00:00",
                    text='<a href="https://example.com/a">article a</a>'),
                box("skitteam/2", time="2026-10-05T02:10:00+00:00",
                    text='<a href="https://example.com/b">article b</a>'),
            ))
        mock_opened.append(str(request.url))
        return httpx.Response(mock_status, html=MOCK_ARTICLE_HTML)

    def collect():
        return run_db(database, lambda factory: run(
            (SKITTEAM,), scope=channel_scope(link_max=1), since=NOW - timedelta(days=1),
            until=NOW, now=NOW, page_delay=0, session_factory=factory,
            transport=httpx.MockTransport(mock_handler),
        ))

    assert collect().db.news_new == 1
    mock_status = 200
    assert collect().db.news_filled == 1
    assert collect().db.news_new == 0
    assert mock_opened == ["https://example.com/a", "https://example.com/a"]
    [stored] = query(database, "SELECT body_status, cleaned_text FROM news")
    assert stored["body_status"] == "ok" and stored["cleaned_text"]


def test_card_registration_is_scoped_and_bodyless_read_defers_body(database, monkeypatch):

    alembic(database, "upgrade", "head")
    mock_ids = in_session(database, lambda s: save_news(s, [
        mock_news("https://example.com/a"), mock_news("https://example.com/b"),
    ])).ids
    assert in_session(database, lambda s: register_missing_sources(
        s, news_ids=mock_ids[:1], report_ids=[], message_ids=[],
    )) == {"news": 1, "pdf": 0, "message": 0}
    [mock_card] = query(database, "SELECT id FROM source_card")

    async def work(factory):
        from sqlalchemy import event, inspect

        mock_loaded = []

        def mock_on_load(target, context):
            mock_loaded.append(inspect(target).unloaded)

        event.listen(News, "load", mock_on_load)
        try:
            async with factory() as session:
                [record] = await get_sources(session, [mock_card[0]])
                assert record.has_body and record.body is None
                assert "cleaned_text" in mock_loaded[0]
            async with factory() as session:
                [record] = await get_sources(session, [mock_card[0]], include_body=True)
                assert record.body
        finally:
            event.remove(News, "load", mock_on_load)

    run_db(database, work)
