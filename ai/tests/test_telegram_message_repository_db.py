"""텔레그램 메시지·발견 링크 저장을 실제 PostgreSQL 에서 본다.

    - 같은 메시지를 다시 수집해도 행이 늘지 않고, 처음 저장한 본문은 바뀌지 않는다
    - 게시 시각 불명·본문 없음(첨부만) 메시지도 그 상태 그대로 남는다
    - 같은 기사를 여러 메시지가 공유하면 기사는 한 행, 발견 기록은 메시지마다 남는다
    - 열지 않은 링크(stale 등)가 이전에 연 결과를 덮지 않는다
    - 보관 정책으로 지운 본문은 다시 수집해도 되살아나지 않는다
    - 수집 범위(채널·수집량·링크 출처) 밖은 받지 않는다
"""

from datetime import UTC, date, datetime, timedelta, timezone

import httpx
import pytest

from app.collectors.news_channels import run as run_channels
from app.collectors.news_channels import save_to_db
from app.collectors.telegram import FoundPdf, record_pdf_messages
from app.core.scope import ScopeError, parse_scope
from app.repositories.retention import PurgeTargets, purge
from app.repositories.telegram_message import (
    ensure_channels,
    known_message_keys,
    save_message_links,
    save_messages,
)
from app.services.news_link.schema import LinkBody
from app.services.telegram_web import Channel, ChannelMessage
from tests.db import in_session, run_db
from tests.test_migrations import alembic, query
from tests.test_news_channels import ARTICLE_HTML
from tests.test_telegram_web import box, page

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=KST)
SKITTEAM = Channel("skitteam", "[ IT는 SK ]", "SK증권 리서치 IT팀", "A")
MERITZ = Channel("merITz_tech", "[메리츠 Tech]", "메리츠증권 리서치", "A")


def message_row(channel_id: int, msg_id: int = 1, **values) -> dict:
    return {
        "channel_id": channel_id, "msg_id": msg_id, "url": f"https://t.me/skitteam/{msg_id}",
        "posted_at": NOW, "author": None, "text": "원래 글", "attachment_name": None,
        "hidden_links": [], "views": "1.2K", "edited": False, "collected_via": "web", **values,
    }


def channel_id(database: str) -> int:
    async def work(session):
        ids = await ensure_channels(session, [
            {"telegram_handle": "skitteam", "name": "[ IT는 SK ]", "is_public": True}
        ])
        return ids["skitteam"]

    return in_session(database, work)


def test_message_is_stored_once_and_the_first_text_survives_an_edit(database):
    alembic(database, "upgrade", "head")
    cid = channel_id(database)

    [first] = in_session(database, lambda s: save_messages(s, [message_row(cid)]))
    [edited] = in_session(database, lambda s: save_messages(s, [
        message_row(cid, text="고친 글", edited=True, views="2K")
    ]))
    [again] = in_session(database, lambda s: save_messages(s, [message_row(cid, views="3K")]))

    assert first.inserted and not edited.inserted
    assert edited.text_changed and not again.text_changed
    [message] = query(database, "SELECT * FROM telegram_messages")
    assert message["text"] == "원래 글", "처음 저장한 본문은 바꾸지 않는다"
    assert message["edited"] is True, "한 번 본 수정 표시는 남는다"
    assert message["edit_detected_at"] is not None
    assert message["views"] == "3K", "조회수는 마지막으로 본 값이다"


def test_undated_and_attachment_only_messages_keep_their_state(database):
    alembic(database, "upgrade", "head")
    cid = channel_id(database)
    in_session(database, lambda s: save_messages(s, [
        message_row(cid, posted_at=None, text="", attachment_name="report.pdf")
    ]))
    [message] = query(database, "SELECT posted_at, text, attachment_name FROM telegram_messages")
    assert (message["posted_at"], message["text"]) == (None, ""), "모르는 값을 지어내지 않는다"

    # 나중에 게시 시각을 읽었으면 채운다. 본문은 그대로다.
    in_session(database, lambda s: save_messages(s, [
        message_row(cid, posted_at=NOW, text="", attachment_name="report.pdf")
    ]))
    assert query(database, "SELECT posted_at FROM telegram_messages")[0][0] == NOW


def test_reviewed_channel_rows_are_not_touched(database):
    alembic(database, "upgrade", "head")
    query(database, """
        INSERT INTO channel (telegram_handle, name, is_public, grade, reviewed_by, created_at)
        VALUES ('skitteam', '검수한 이름', false, 'A', 'reviewer', now())
    """)
    channel_id(database)
    [row] = query(database, "SELECT name, is_public, grade FROM channel")
    assert tuple(row) == ("검수한 이름", False, "A")


def test_link_results_only_move_forward(database):
    alembic(database, "upgrade", "head")
    cid = channel_id(database)
    [message] = in_session(database, lambda s: save_messages(s, [message_row(cid)]))

    def link(status: str, **values) -> dict:
        return {"message_id": message.id, "kind": "url", "position": 1,
                "discovered_url": "https://buly.kr/a", "final_url": None, "status": status,
                "error": None, "http_status": None, "fetched_at": None, "news_id": None,
                "analyst_report_id": None, **values}

    def save(row):
        return in_session(database, lambda s: save_message_links(s, [row]))

    assert save(link("error", error="ConnectTimeout")) == (1, 0)
    assert save(link("stale")) == (0, 0), "열지 않은 이유가 이전 결과를 덮지 않는다"
    assert save(link("ok", final_url="https://news.example.com/a")) == (0, 1)
    assert save(link("http_error", http_status=403)) == (0, 0), "성공한 결과는 그대로다"
    [row] = query(database, "SELECT status, final_url FROM telegram_message_links")
    assert tuple(row) == ("ok", "https://news.example.com/a")


def _body(url: str, **values) -> LinkBody:
    return LinkBody(url=url, fetched_at=datetime(2026, 10, 5, 2, 0, tzinfo=UTC), **values)


def test_save_to_db_keeps_one_article_and_every_discovery(database):
    alembic(database, "upgrade", "head")
    article = _body(
        "https://buly.kr/a", final_url="https://news.example.com/a/1?utm_source=tg",
        domain="www.news.example.com", status="ok", title="삼성전자 HBM",
        excerpt="앞 세 문장만.", text="앞 세 문장만. 그리고 기사 본문 전체가 이어진다.",
    )
    blocked = _body("https://buly.kr/x", status="blocked", error="내부 주소로 향함: http://10.0.0.1/")
    messages = [
        ChannelMessage(channel="skitteam", msg_id=1, url="https://t.me/skitteam/1",
                       posted_at=NOW - timedelta(hours=1), text="기사 https://buly.kr/a",
                       links=["https://buly.kr/a", "https://PLTR.US"], link_bodies=[article]),
        ChannelMessage(channel="merITz_tech", msg_id=1, url="https://t.me/merITz_tech/1",
                       posted_at=NOW - timedelta(hours=2), text="같은 기사",
                       links=["https://buly.kr/a", "https://buly.kr/x"],
                       link_bodies=[article, blocked]),
        ChannelMessage(channel="skitteam", msg_id=2, url="https://t.me/skitteam/2",
                       posted_at=None, text="", attachment="report.pdf"),
        ChannelMessage(channel="skitteam", msg_id=None, text="번호를 못 읽은 글"),
    ]

    def run(msgs, now):
        return run_db(database, lambda factory: save_to_db(
            msgs, (SKITTEAM, MERITZ), now=now, per_message=3, unopened="out_of_scope",
            session_factory=factory,
        ))

    stats = run(messages, NOW)

    assert (stats.messages_new, stats.no_msg_id, stats.news_new) == (3, 1, 1)
    assert stats.cards == {"news": 1, "pdf": 0, "message": 3}
    assert stats.register_error is None
    [news] = query(database, "SELECT * FROM news")
    assert news["cleaned_text"] == article.text, "발췌가 아니라 본문 전체다"
    assert news["published_at"] is None
    assert (news["source"], news["publisher"]) == ("telegram", "news.example.com")
    assert news["canonical_url"] == "https://news.example.com/a/1"
    links = query(database, """
        SELECT m.url, l.position, l.discovered_url, l.final_url, l.status, l.news_id
        FROM telegram_message_links l JOIN telegram_messages m ON m.id = l.message_id
        ORDER BY m.url, l.position
    """)
    assert [tuple(r) for r in links] == [
        ("https://t.me/merITz_tech/1", 1, "https://buly.kr/a",
         "https://news.example.com/a/1?utm_source=tg", "ok", news["id"]),
        ("https://t.me/merITz_tech/1", 2, "https://buly.kr/x", None, "blocked", None),
        ("https://t.me/skitteam/1", 1, "https://buly.kr/a",
         "https://news.example.com/a/1?utm_source=tg", "ok", news["id"]),
        ("https://t.me/skitteam/1", 2, "https://PLTR.US", None, "not_fetchable", None),
    ]

    # 다음 날 다시 수집하면 24시간이 지나 링크를 열지 않는다. 어제 결과는 그대로다.
    for message in messages:
        message.link_bodies = []
    again = run(messages, NOW + timedelta(days=1))
    assert (again.messages_new, again.messages_known, again.news_new) == (0, 3, 0)
    assert (again.links_new, again.links_updated) == (0, 0)
    assert again.cards == {"news": 0, "pdf": 0, "message": 0}
    assert len(query(database, "SELECT * FROM telegram_message_links")) == 4
    assert query(database, "SELECT count(*) FROM source_card")[0][0] == 4


def test_edited_message_keeps_its_first_links(database):
    alembic(database, "upgrade", "head")
    original = ChannelMessage(channel="skitteam", msg_id=1, url="https://t.me/skitteam/1",
                              posted_at=NOW, text="글 https://buly.kr/a",
                              links=["https://buly.kr/a"])

    def run(message):
        return run_db(database, lambda factory: save_to_db(
            [message], (SKITTEAM,), now=NOW, per_message=3, unopened="not_opened",
            session_factory=factory,
        ))

    run(original)
    edited = original.model_copy(update={"text": "고친 글 https://buly.kr/b",
                                         "links": ["https://buly.kr/b"], "edited": True})
    stats = run(edited)

    assert stats.edits_detected == 1
    assert [tuple(r) for r in query(database, """
        SELECT discovered_url, status FROM telegram_message_links
    """)] == [("https://buly.kr/a", "not_opened")]


def _found(msg_id: int, sha: str | None, *, excluded: bool = False) -> FoundPdf:
    return FoundPdf(msg_id=msg_id, posted_at=datetime(2026, 10, 5, 0, 0, tzinfo=UTC),
                    text="리포트 공유", author=None, views="10", edited=False,
                    filename=f"report-{msg_id}.pdf", pdf_sha256=sha, excluded=excluded)


def test_pdf_messages_keep_their_discovery_even_when_naver_has_the_same_pdf(database):
    alembic(database, "upgrade", "head")
    for source, category, source_id, sha in [
        ("naver", "company", "100", "a" * 64),
        ("telegram", "sunstudy1234", "11", "b" * 64),
    ]:
        query(database, """
            INSERT INTO analyst_reports (source, source_category, source_id, category, title,
                                         write_date, body_status, pdf_sha256, broker)
            VALUES ($1, $2, $3, 'company', 'title', '2026-10-05', 'ok', $4, '하나증권')
        """, source, category, source_id, sha)
    found = [_found(10, "a" * 64), _found(11, "b" * 64), _found(12, "c" * 64, excluded=True)]

    error = in_session(database, lambda s: record_pdf_messages(
        s, "sunstudy1234", is_public=True, found=found))

    assert error is None
    rows = query(database, """
        SELECT m.msg_id, m.collected_via, m.attachment_name, l.kind, l.status, r.source
        FROM telegram_message_links l
        JOIN telegram_messages m ON m.id = l.message_id
        LEFT JOIN analyst_reports r ON r.id = l.analyst_report_id
        ORDER BY m.msg_id
    """)
    assert [tuple(r) for r in rows] == [
        (10, "telethon", "report-10.pdf", "attachment", "duplicate", "naver"),
        (11, "telethon", "report-11.pdf", "attachment", "saved", "telegram"),
        (12, "telethon", "report-12.pdf", "attachment", "excluded", None),
    ]
    assert query(database, "SELECT card_type, count(*) FROM source_card GROUP BY 1 ORDER BY 1") \
        == [("message", 3), ("pdf", 2)]


def test_failing_discovery_record_does_not_lose_the_pdf_rows(database):
    """PDF 는 다시 받기 비싸다. 발견 경로 저장이 실패해도 같은 트랜잭션의 PDF 행은 남는다."""
    alembic(database, "upgrade", "head")

    async def work(session):
        from app.repositories.analyst_report import upsert_analyst_reports

        await upsert_analyst_reports(session, [{
            "source": "telegram", "source_category": "sunstudy1234", "source_id": "1",
            "category": "company", "title": "title", "write_date": NOW.date(),
            "body_status": "ok",
        }])
        # channel.telegram_handle 은 100자다. 채널 등록에서 실패한다.
        return await record_pdf_messages(session, "x" * 150, is_public=True,
                                         found=[_found(1, None)])

    error = in_session(database, work)

    assert error and "메시지·발견 경로 저장 실패" in error
    assert query(database, "SELECT count(*) FROM analyst_reports")[0][0] == 1
    assert query(database, "SELECT count(*) FROM telegram_messages")[0][0] == 0


def test_purged_message_is_not_restored_or_flagged_as_edited(database):
    alembic(database, "upgrade", "head")
    cid = channel_id(database)
    [saved] = in_session(database, lambda s: save_messages(s, [message_row(cid)]))
    in_session(database, lambda s: purge(s, PurgeTargets(message=[saved.id]), reason="보관 정책"))

    [again] = in_session(database, lambda s: save_messages(s, [message_row(cid)]))

    assert not again.text_changed, "지운 본문을 고친 글로 보지 않는다"
    [row] = query(database, "SELECT text, purged_at, purge_reason, edit_detected_at, url "
                            "FROM telegram_messages")
    assert row["text"] is None and row["purged_at"] is not None
    assert (row["purge_reason"], row["edit_detected_at"]) == ("보관 정책", None)
    assert row["url"] == "https://t.me/skitteam/1", "주소는 남는다"


def test_forwarded_origin_is_stored_and_known_keys_are_found(database):
    alembic(database, "upgrade", "head")
    cid = channel_id(database)
    in_session(database, lambda s: save_messages(s, [
        message_row(cid, 1, forwarded_from="다른 채널", forwarded_from_url="https://t.me/o/9"),
        message_row(cid, 2),
    ]))
    rows = query(database, "SELECT msg_id, forwarded_from, forwarded_from_url "
                           "FROM telegram_messages ORDER BY msg_id")
    assert [tuple(r) for r in rows] == [(1, "다른 채널", "https://t.me/o/9"), (2, None, None)]
    keys = in_session(database, lambda s: known_message_keys(
        s, [("skitteam", 1), ("skitteam", 3), ("merITz_tech", 1)]))
    assert keys == {("skitteam", 1)}


# ── 수집 범위 안에서 돌기 (news_channels.run) ─────────────────────────


def channel_scope(*, web_max=10, link_max=None, end=date(2026, 10, 31)):
    terms = {"status": "미확인"}
    sources = {"telegram_web": {"enabled": True, "channels": ["skitteam"], "max_items": web_max,
                                "terms": terms}}
    if link_max is not None:
        sources["telegram_link"] = {"enabled": True, "max_items": link_max, "terms": terms}
    return parse_scope({"period": {"start": date(2026, 10, 1), "end": end}, "sources": sources})


def channel_server(opened: list[str]) -> httpx.MockTransport:
    """skitteam 채널 페이지 하나와 기사. 연 기사 주소를 opened 에 모은다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "t.me":
            if request.url.params.get("before"):
                return httpx.Response(200, html=page())
            return httpx.Response(200, html=page(
                box("skitteam/3", time="2026-10-05T02:00:00+00:00",
                    text='기사 <a href="https://news.example.com/b">https://news.example.com/b</a>'),
                box("skitteam/2", time="2026-10-05T01:00:00+00:00",
                    text='기사 <a href="https://news.example.com/a">https://news.example.com/a</a>'),
                box("skitteam/1", text="게시 시각을 못 읽은 글"),
            ))
        opened.append(str(request.url))
        return httpx.Response(200, html=ARTICLE_HTML)

    return httpx.MockTransport(handler)


def run_in_scope(database, scope, opened, channels=(SKITTEAM,)):
    return run_db(database, lambda factory: run_channels(
        channels, scope=scope, since=NOW - timedelta(days=1), until=NOW, now=NOW,
        page_delay=0, session_factory=factory, transport=channel_server(opened),
    ))


def test_channel_outside_the_scope_is_refused_before_reading(database):
    alembic(database, "upgrade", "head")
    opened: list[str] = []
    with pytest.raises(ScopeError, match="merITz_tech"):
        run_in_scope(database, channel_scope(), opened, channels=(MERITZ,))
    assert not query(database, "SELECT * FROM telegram_messages")


def test_volume_limit_and_disabled_link_source_hold_the_rest(database):
    """새 메시지는 상한까지만, 링크 출처가 꺼져 있으면 링크는 열지 않고 발견 기록만 남긴다."""
    alembic(database, "upgrade", "head")
    opened: list[str] = []

    result = run_in_scope(database, channel_scope(web_max=1), opened)

    assert [m.msg_id for m in result.messages] == [2], "가장 이른 새 메시지 하나만"
    assert (result.held_messages, result.held_links) == (2, 1)
    assert opened == [], "telegram_link 가 꺼져 있으면 기사를 열지 않는다"
    assert [tuple(r) for r in query(database, """
        SELECT discovered_url, status FROM telegram_message_links
    """)] == [("https://news.example.com/a", "out_of_scope")]
    assert not query(database, "SELECT * FROM news")

    # 상한에 닿은 뒤에는 이미 저장된 메시지만 갱신한다
    again = run_in_scope(database, channel_scope(web_max=1), opened)
    assert ([m.msg_id for m in again.messages], again.held_messages) == ([2], 2)
    assert query(database, "SELECT count(*) FROM telegram_messages")[0][0] == 1


def test_link_source_opens_only_the_remaining_volume(database):
    alembic(database, "upgrade", "head")
    opened: list[str] = []

    result = run_in_scope(database, channel_scope(link_max=1), opened)

    assert len(opened) == 1 and result.held_links == 1
    assert sorted(r[0] for r in query(database, "SELECT status FROM telegram_message_links")) \
        == ["ok", "out_of_scope"]
    assert query(database, "SELECT count(*) FROM news")[0][0] == 1


def test_undated_messages_wait_when_today_is_outside_the_period(database):
    """게시 시각을 모르면 기간 안인지 모른다. 오늘이 기간 밖이면 받지 않는다."""
    alembic(database, "upgrade", "head")
    opened: list[str] = []

    result = run_in_scope(database, channel_scope(end=date(2026, 10, 4)), opened)

    assert (result.messages, result.held_undated) == ([], 1)
    assert not query(database, "SELECT * FROM telegram_messages")
