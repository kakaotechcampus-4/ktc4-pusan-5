"""공통 자료 ID(source_card) 등록·제약·조회를 실제 PostgreSQL 에서 본다.

    - 등록은 몇 번을 돌려도 원문 하나에 카드 하나다
    - 카드는 종류에 맞는 원문 하나만 가리키고, 원문을 복제하지 않는다
    - 공통 ID 로 본문·발행처·수집 경로·발견 경로를 읽는다
"""

from datetime import UTC, datetime, timedelta, timezone

import asyncpg
import pytest

from app.repositories.news import save_news
from app.repositories.source_card import (
    backfill_canonical_urls,
    get_sources,
    register_missing_sources,
)
from tests.db import in_session
from tests.test_migrations import alembic, query

FETCHED = datetime(2026, 10, 5, 2, 0, tzinfo=UTC)


def register(database: str) -> dict[str, int]:
    return in_session(database, register_missing_sources)


def seed(database: str) -> None:
    """기사 하나를 두 채널 메시지가 공유하고, PDF 는 네이버·텔레그램에서 하나씩 왔다."""
    in_session(database, lambda s: save_news(s, [{
        "url": "https://news.example.com/a/1", "title": "삼성전자 HBM", "publisher": "news.example.com",
        "source": "telegram", "published_at": None, "summary": "", "cleaned_text": "기사 본문 전체",
        "body_status": "ok", "body_error": None, "body_fetched_at": FETCHED,
        "body_extractor": "news_link",
    }]))
    query(database, """
        INSERT INTO channel (telegram_handle, name, is_public, created_at) VALUES
            ('skitteam', '[ IT는 SK ]', true, now()),
            ('sunstudy1234', 'sunstudy1234', true, now())
    """)
    query(database, """
        INSERT INTO analyst_reports (source, source_category, source_id, category, title, write_date,
                                     body_status, body_text, broker, end_url)
        VALUES ('naver', 'company', '100', 'company', '네이버 리포트', '2026-10-04', 'ok', '본문',
                '미래에셋증권', 'https://m.stock.naver.com/research/company/100'),
               ('telegram', 'sunstudy1234', '7', 'industry', '텔레그램 리포트', '2026-10-05', 'ok',
                '본문', '하나증권', 'https://t.me/sunstudy1234/7')
    """)
    query(database, """
        INSERT INTO telegram_messages (channel_id, msg_id, url, posted_at, text, collected_via)
        SELECT id, 1, 'https://t.me/skitteam/1', '2026-10-05 10:00+09', '기사 공유', 'web'
        FROM channel WHERE telegram_handle = 'skitteam'
    """)
    query(database, """
        INSERT INTO telegram_message_links (message_id, kind, position, discovered_url, final_url,
                                            status, news_id)
        SELECT m.id, 'url', 1, 'https://buly.kr/a', 'https://news.example.com/a/1', 'ok', n.id
        FROM telegram_messages m, news n
    """)


def test_registration_is_idempotent_and_does_not_copy_the_raw_text(database):
    alembic(database, "upgrade", "head")
    seed(database)

    assert register(database) == {"news": 1, "pdf": 2, "message": 1}
    assert register(database) == {"news": 0, "pdf": 0, "message": 0}

    cards = query(database, """
        SELECT c.card_type, c.source_name, ch.telegram_handle, c.raw_text, c.cleaned_text,
               c.source_url, c.tags, c.payload
        FROM source_card c LEFT JOIN channel ch ON ch.id = c.channel_id
        ORDER BY c.card_type, c.source_name
    """)
    assert [tuple(r)[:3] for r in cards] == [
        ("message", "[ IT는 SK ]", "skitteam"),
        ("news", "news.example.com", None),
        ("pdf", "미래에셋증권", None),
        ("pdf", "하나증권", "sunstudy1234"),
    ]
    assert all(r["raw_text"] is None and r["cleaned_text"] is None and r["source_url"] is None
               for r in cards), "원문은 카드에 복제하지 않는다"


@pytest.mark.parametrize("card_type,column", [
    ("news", "analyst_report_id"),  # 종류와 다른 원문
    ("pdf", None),  # 원문 없는 pdf 카드
    ("price", "news_id"),  # 원문 표가 없는 종류가 원문을 가리킴
])
def test_card_must_point_to_one_raw_row_of_its_own_kind(database, card_type, column):
    alembic(database, "upgrade", "head")
    seed(database)
    target = {"news_id": "(SELECT id FROM news)",
              "analyst_report_id": "(SELECT min(id) FROM analyst_reports)"}
    columns = f", {column}" if column else ""
    values = f", {target[column]}" if column else ""
    with pytest.raises(asyncpg.CheckViolationError):
        query(database, f"""
            INSERT INTO source_card (card_type, tags, payload, created_at{columns})
            VALUES ('{card_type}', '[]', '{{}}', now(){values})
        """)


def test_other_card_types_without_raw_rows_are_still_allowed(database):
    """backend 가 시세·공시 같은 카드를 따로 만들 수 있다."""
    alembic(database, "upgrade", "head")
    query(database, """
        INSERT INTO source_card (card_type, tags, payload, created_at)
        VALUES ('price', '[]', '{}', now())
    """)
    assert register(database) == {"news": 0, "pdf": 0, "message": 0}


def test_a_raw_row_cannot_get_two_cards(database):
    alembic(database, "upgrade", "head")
    seed(database)
    register(database)
    with pytest.raises(asyncpg.UniqueViolationError):
        query(database, """
            INSERT INTO source_card (card_type, news_id, tags, payload, created_at)
            VALUES ('news', (SELECT id FROM news), '[]', '{}', now())
        """)


def test_get_sources_reads_body_publisher_path_and_discoveries(database):
    alembic(database, "upgrade", "head")
    seed(database)
    register(database)
    ids = {row["card_type"] + str(row["n"]): row["id"] for row in query(database, """
        SELECT id, card_type, row_number() OVER (PARTITION BY card_type ORDER BY id) AS n
        FROM source_card
    """)}

    records = in_session(database, lambda s: get_sources(
        s, [ids["news1"], ids["pdf2"], ids["message1"], 999_999], include_body=True
    ))

    news, pdf, message = records
    assert (news.kind, news.publisher, news.collection_path) == (
        "news", "news.example.com", "telegram_link")
    assert news.body == "기사 본문 전체"
    assert (news.has_body, news.body_missing_reason) == (True, None)
    assert news.published_at is None and news.body_fetched_at == FETCHED
    [found] = news.discoveries
    assert (found.channel, found.message_url, found.discovered_url, found.final_url) == (
        "skitteam", "https://t.me/skitteam/1", "https://buly.kr/a", "https://news.example.com/a/1")
    assert found.message_card_id == ids["message1"]

    # 증권사 PDF 를 텔레그램에서 받았다: 형태 pdf · 발행처 증권사 · 경로 텔레그램 첨부
    assert (pdf.kind, pdf.publisher, pdf.collection_path, pdf.channel) == (
        "pdf", "하나증권", "telegram_attachment", "sunstudy1234")

    assert (message.kind, message.body, message.collection_path) == (
        "message", "기사 공유", "telegram_web")
    [link] = message.discoveries
    assert link.target_card_id == ids["news1"], "메시지에서 이 기사의 공통 ID 로 건너간다"


def test_canonical_backfill_fills_legacy_rows_and_reports_duplicates(database):
    query(database, """
        INSERT INTO news (url, title, publisher, source, published_at, summary) VALUES
            ('https://Example.com/n/1?utm_source=naver', 'a', 'example.com', 'naver', now(), ''),
            ('https://example.com/n/1', 'b', 'example.com', 'naver', now(), ''),
            ('https://example.com/n/2', 'c', 'example.com', 'naver', now(), '')
    """)
    alembic(database, "upgrade", "head")

    first = in_session(database, backfill_canonical_urls)
    again = in_session(database, backfill_canonical_urls)

    assert first.filled == 2
    assert first.collisions == [(2, "https://example.com/n/1")], "합치지 않고 알린다"
    assert (again.filled, again.collisions) == (0, first.collisions)
    assert [tuple(r) for r in query(database, "SELECT id, canonical_url FROM news ORDER BY id")] == [
        (1, "https://example.com/n/1"), (2, None), (3, "https://example.com/n/2"),
    ]


def _card_ids(database) -> dict[str, int]:
    return {row["card_type"] + str(row["n"]): row["id"] for row in query(database, """
        SELECT id, card_type, row_number() OVER (PARTITION BY card_type ORDER BY id) AS n
        FROM source_card
    """)}


def test_body_is_returned_only_on_request_but_its_absence_always_has_a_reason(database):
    """원문은 내부 분류·검증에만 쓴다. 본문은 요청할 때만 주고, 없으면 왜 없는지는 늘 준다."""
    alembic(database, "upgrade", "head")
    seed(database)
    query(database, """
        INSERT INTO news (url, title, publisher, source, published_at, summary, body_status,
                          body_error)
        VALUES ('https://news.example.com/fail', '', 'news.example.com', 'telegram', NULL, '',
                'failed', 'http_error: 403')
    """)
    query(database, """
        INSERT INTO telegram_messages (channel_id, msg_id, url, text, attachment_name,
                                       collected_via)
        SELECT id, 2, 'https://t.me/skitteam/2', '', 'report.pdf', 'web'
        FROM channel WHERE telegram_handle = 'skitteam'
    """)
    register(database)
    ids = _card_ids(database)

    records = in_session(database, lambda s: get_sources(
        s, [ids["news1"], ids["news2"], ids["message2"]]))

    assert all(r.body is None for r in records), "요청하지 않으면 본문을 주지 않는다"
    assert [(r.has_body, r.body_missing_reason) for r in records] == [
        (True, None),
        (False, "failed: http_error: 403"),
        (False, "empty: 글자 없이 첨부만 올린 메시지"),
    ]


def test_purge_removes_only_bodies_and_keeps_ids_cards_and_sources(database):
    from datetime import UTC, datetime, timedelta

    from app.repositories.retention import purge, purge_targets

    alembic(database, "upgrade", "head")
    seed(database)
    register(database)
    ids = _card_ids(database)
    links_before = query(database, "SELECT * FROM telegram_message_links")

    async def select(session):
        return await purge_targets(session, card_ids=[ids["news1"], ids["pdf1"], ids["message1"]])

    targets = in_session(database, select)
    assert targets.counts() == {"news": 1, "pdf": 1, "message": 1}
    done = in_session(database, lambda s: purge(s, targets, reason="2026-10 실험 종료"))
    assert done == {"news": 1, "pdf": 1, "message": 1}
    # 다시 지워도 이미 지운 것은 고르지 않는다
    assert in_session(database, select).counts() == {"news": 0, "pdf": 0, "message": 0}

    [news] = query(database, "SELECT cleaned_text, body_status, title, url FROM news")
    assert (news["cleaned_text"], news["body_status"]) == (None, "purged")
    assert (news["title"], news["url"]) == ("삼성전자 HBM", "https://news.example.com/a/1")
    report = query(database, "SELECT body_text, body_status FROM analyst_reports "
                             "WHERE source = 'naver'")[0]
    assert tuple(report) == (None, "purged")
    assert query(database, "SELECT text FROM telegram_messages")[0][0] is None
    assert query(database, "SELECT count(*) FROM source_card")[0][0] == 4, "카드는 남는다"
    assert query(database, "SELECT * FROM telegram_message_links") == links_before

    records = in_session(database, lambda s: get_sources(
        s, [ids["news1"], ids["message1"]], include_body=True))
    assert all(r.body is None and not r.has_body for r in records)
    assert all(r.body_missing_reason.startswith("purged: 보관 정책으로 삭제")
               and r.body_missing_reason.endswith("2026-10 실험 종료") for r in records)

    # 수집 시각 기준으로 고르기. 지금보다 이전에 수집한 PDF 중 남은 것(텔레그램 PDF)
    async def by_date(session):
        return await purge_targets(session, kind="pdf",
                                   collected_before=datetime.now(UTC) + timedelta(days=1))

    assert in_session(database, by_date).counts() == {"news": 0, "pdf": 1, "message": 0}


def test_forwarded_message_card_names_the_original_channel_as_publisher(database):
    alembic(database, "upgrade", "head")
    seed(database)
    query(database, "UPDATE telegram_messages SET forwarded_from = '다른 채널', "
                    "forwarded_from_url = 'https://t.me/other/9'")
    register(database)
    [card] = query(database, "SELECT source_name FROM source_card WHERE card_type = 'message'")
    assert card[0] == "다른 채널", "전달된 글의 원 발행처는 원래 채널이다"

    ids = _card_ids(database)
    [record] = in_session(database, lambda s: get_sources(s, [ids["message1"]]))
    assert (record.publisher, record.channel, record.forwarded_from_url) == (
        "다른 채널", "skitteam", "https://t.me/other/9")


def test_cards_get_earliest_public_time_date_and_report_stock(database):
    """공개 시각은 원문 시각과 그 자료를 건 메시지 게시 시각 중 가장 이른 것이다."""
    alembic(database, "upgrade", "head")
    seed(database)
    query(database, "UPDATE analyst_reports SET item_code = '005930' WHERE source = 'naver'")
    register(database)

    rows = query(database, """
        SELECT card_type, available_at, event_date::text AS day FROM source_card
        ORDER BY card_type, analyst_report_id
    """)
    posted = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)  # 2026-10-05 10:00 KST
    assert [(r["card_type"], r["available_at"], r["day"]) for r in rows] == [
        ("message", posted, "2026-10-05"),
        ("news", posted, "2026-10-05"),  # 발행 시각을 모르는 기사는 그 기사를 건 메시지 시각
        ("pdf", None, "2026-10-04"),  # 네이버 리포트는 시각 없이 작성일만
        ("pdf", None, "2026-10-05"),
    ]
    tags = query(database, """
        SELECT s.stock_code, s.tagged_by, c.analyst_report_id IS NOT NULL AS is_pdf
        FROM source_card_stocks s JOIN source_card c ON c.id = s.source_card_id
    """)
    assert [tuple(t) for t in tags] == [("005930", "report_item_code", True)]

    # 더 이른 메시지가 같은 기사를 건 것을 나중에 수집하면 공개 시각이 앞당겨진다.
    query(database, """
        INSERT INTO telegram_messages (channel_id, msg_id, url, posted_at, text, collected_via)
        SELECT id, 2, 'https://t.me/skitteam/2', '2026-10-04 23:00+09', '먼저 공유', 'web'
        FROM channel WHERE telegram_handle = 'skitteam'
    """)
    query(database, """
        INSERT INTO telegram_message_links (message_id, kind, position, discovered_url, final_url,
                                            status, news_id)
        SELECT m.id, 'url', 1, 'https://buly.kr/b', 'https://news.example.com/a/1', 'ok', n.id
        FROM telegram_messages m, news n WHERE m.msg_id = 2
    """)
    register(database)
    [news] = query(database, "SELECT available_at, event_date::text AS day FROM source_card "
                             "WHERE card_type = 'news'")
    assert (news["available_at"], news["day"]) == (datetime(2026, 10, 4, 14, 0, tzinfo=UTC),
                                                   "2026-10-04")
    assert query(database, "SELECT count(*) FROM source_card_stocks")[0][0] == 1, "다시 돌려도 같다"


def test_stock_card_ids_respects_the_cutoff(database):
    """기준 시각 이후 자료와, 시각을 몰라 같은 날인지 알 수 없는 자료는 빠진다."""
    from app.repositories.source_card import stock_card_ids

    alembic(database, "upgrade", "head")
    seed(database)
    query(database, "UPDATE analyst_reports SET item_code = '005930' WHERE source = 'naver'")
    register(database)
    ids = _card_ids(database)
    query(database, f"""
        INSERT INTO source_card_stocks (source_card_id, stock_code, tagged_by)
        VALUES ({ids["news1"]}, '005930', 'test'), ({ids["message1"]}, '000660', 'test')
    """)

    def find(until, since=None):
        return in_session(database, lambda s: stock_card_ids(s, "005930", until=until, since=since))

    kst = timezone(timedelta(hours=9))
    # 10-05 09:00: 네이버 리포트(10-04 작성)만. 기사는 10:00 에 공개됐다
    assert find(datetime(2026, 10, 5, 9, 0, tzinfo=kst)) == [ids["pdf1"]]
    # 10-05 15:30: 리포트와 기사. 다른 종목의 메시지는 빠진다
    assert find(datetime(2026, 10, 5, 15, 30, tzinfo=kst)) == [ids["pdf1"], ids["news1"]]
    # 10-04 15:30: 작성일이 같은 날인 리포트는 기준 시각 전인지 몰라 뺀다
    assert find(datetime(2026, 10, 4, 15, 30, tzinfo=kst)) == []
    # since 로 앞쪽을 자른다
    assert find(datetime(2026, 10, 5, 15, 30, tzinfo=kst),
                since=datetime(2026, 10, 5, 0, 0, tzinfo=kst)) == [ids["news1"]]


def test_get_sources_reports_the_public_time(database):
    alembic(database, "upgrade", "head")
    seed(database)
    register(database)
    ids = _card_ids(database)
    [record] = in_session(database, lambda s: get_sources(s, [ids["news1"]]))
    assert record.published_at is None
    assert record.available_at == datetime(2026, 10, 5, 1, 0, tzinfo=UTC)


def test_card_ids_for_urls_matches_messages_and_canonical_news(database):
    from app.repositories.source_card import card_ids_for_urls

    alembic(database, "upgrade", "head")
    seed(database)
    in_session(database, backfill_canonical_urls)
    register(database)
    ids = _card_ids(database)
    found = in_session(database, lambda s: card_ids_for_urls(s, [
        "https://t.me/skitteam/1",
        "https://NEWS.example.com/a/1?utm_source=tg",  # 정규화하면 같은 기사
        "https://t.me/skitteam/999",  # DB 에 없다
    ]))
    assert found == {
        "https://t.me/skitteam/1": ids["message1"],
        "https://NEWS.example.com/a/1?utm_source=tg": ids["news1"],
    }
