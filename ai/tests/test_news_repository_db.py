"""news 저장 규칙을 실제 PostgreSQL 에서 본다.

지키려는 것은 셋이다.
    - 같은 기사는 경로·주소 표기가 달라도 한 행이다
    - 실패했던 본문은 나중에 채우지만, 한 번 확보한 본문은 덮어쓰지 않는다
    - 발행 시각을 모르면 NULL 로 둔다. 수집 시각으로 채우지 않는다
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.repositories.news import failed_news, save_news
from tests.db import in_session
from tests.test_migrations import alembic, query

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 10, 5, 9, 0, tzinfo=KST)
URL = "https://news.example.com/a/1"


def row(url: str = URL, **values) -> dict:
    return {
        "url": url,
        "title": "제목",
        "publisher": "news.example.com",
        "source": "naver",
        "published_at": T0,
        "summary": "요약",
        "cleaned_text": "기사 본문 전체",
        "body_status": "ok",
        "body_error": None,
        "body_fetched_at": T0,
        "body_extractor": "trafilatura",
        **values,
    }


def failed(url: str = URL, **values) -> dict:
    return row(url, **{"cleaned_text": None, "body_status": "failed", "body_error": "http_404",
                       **values})


def from_telegram(url: str = URL, **values) -> dict:
    """텔레그램 링크로 연 기사. 발행 시각·요약을 모른다."""
    return row(url, **{"source": "telegram", "published_at": None, "summary": "", "title": "",
                       "body_extractor": "news_link", **values})


def save(database: str, rows: list[dict]):
    return in_session(database, lambda session: save_news(session, rows))


def stored(database: str) -> list:
    return query(database, "SELECT * FROM news ORDER BY id")


def test_failed_body_is_filled_later_but_a_secured_body_is_never_replaced(database):
    alembic(database, "upgrade", "head")
    assert save(database, [failed()]).inserted == 1

    later = T0 + timedelta(hours=1)
    second = save(database, [row(cleaned_text="나중에 받은 본문", body_fetched_at=later)])
    assert (second.inserted, second.filled) == (0, 1)

    # 성공한 본문은 다시 실패해도, 다른 본문을 받아도 그대로다
    save(database, [failed(body_error="http_500", body_fetched_at=later + timedelta(hours=1))])
    save(database, [row(cleaned_text="고쳐진 기사 본문", body_fetched_at=later + timedelta(hours=2))])

    [news] = stored(database)
    assert news["cleaned_text"] == "나중에 받은 본문"
    assert news["body_status"] == "ok"
    assert news["body_error"] is None
    assert news["body_fetched_at"] == later, "본문을 받은 시각도 그 본문의 것이다"


def test_repeated_failures_keep_the_latest_reason(database):
    alembic(database, "upgrade", "head")
    save(database, [failed()])
    save(database, [failed(body_error="extract_empty", body_fetched_at=T0 + timedelta(hours=1))])
    [news] = stored(database)
    assert (news["body_status"], news["body_error"]) == ("failed", "extract_empty")
    assert news["body_fetched_at"] == T0 + timedelta(hours=1)


def test_tracking_parameters_and_case_do_not_make_a_second_article(database):
    alembic(database, "upgrade", "head")
    first = save(database, [row("https://News.Example.com/a/1?utm_source=naver#top")])
    second = save(database, [from_telegram("https://news.example.com/a/1")])
    assert first.ids == second.ids
    [news] = stored(database)
    assert news["url"] == "https://News.Example.com/a/1?utm_source=naver#top", "처음 주소를 둔다"
    assert news["canonical_url"] == URL
    assert news["source"] == "naver", "처음 들어온 경로를 둔다"


def test_same_article_twice_in_one_batch_is_one_row(database):
    alembic(database, "upgrade", "head")
    result = save(database, [failed(), row(URL + "?utm_medium=x")])
    assert result.ids[0] == result.ids[1]
    assert (result.inserted, result.filled) == (1, 1)
    assert len(stored(database)) == 1


def test_missing_publish_time_title_and_summary_are_filled_from_another_path(database):
    alembic(database, "upgrade", "head")
    save(database, [from_telegram()])
    [news] = stored(database)
    assert news["published_at"] is None, "수집 시각으로 채우지 않는다"
    assert news["title"] == ""

    save(database, [row()])
    [news] = stored(database)
    assert news["published_at"] == T0
    assert (news["title"], news["summary"]) == ("제목", "요약")
    assert news["source"] == "telegram"


def test_legacy_row_without_canonical_url_is_found_by_its_original_address(database):
    alembic(database, "upgrade", "head")
    legacy_url = "https://example.com/n?utm_source=naver"
    query(database, """
        INSERT INTO news (id, url, title, publisher, source, published_at, summary, body_status,
                          body_error)
        VALUES (5, $1, 'legacy', 'example.com', 'naver', now(), '', 'failed', 'unrecorded')
    """, legacy_url)

    result = save(database, [row(legacy_url)])

    assert result.ids == [5] and result.filled == 1
    [news] = stored(database)
    assert news["canonical_url"] == "https://example.com/n"
    assert news["cleaned_text"] == "기사 본문 전체"


def test_ok_without_the_whole_body_is_rejected(database):
    alembic(database, "upgrade", "head")
    with pytest.raises(ValueError, match="본문 없이 ok"):
        save(database, [row(cleaned_text=None)])


def test_failed_news_lists_only_recent_failures_of_the_source(database):
    alembic(database, "upgrade", "head")
    save(database, [
        failed("https://a.example.com/1"),
        failed("https://a.example.com/old", published_at=T0 - timedelta(days=3)),
        row("https://a.example.com/ok"),
    ])
    save(database, [from_telegram("https://b.example.com/1", cleaned_text=None,
                                  body_status="failed", body_error="no_body")])

    async def work(session):
        return await failed_news(session, source="naver", since=T0 - timedelta(hours=1), limit=10)

    targets = in_session(database, work)
    assert [n.url for n in targets] == ["https://a.example.com/1"]


def test_collected_time_is_not_used_as_publish_time(database):
    """링크로 연 기사는 발행 시각이 비어 있어야 한다. 받은 시각과 섞이면 컷오프가 틀어진다."""
    alembic(database, "upgrade", "head")
    save(database, [from_telegram(body_fetched_at=datetime.now(UTC))])
    assert query(database, "SELECT published_at FROM news")[0][0] is None


def test_purged_body_is_not_restored_by_a_later_collection(database):
    from app.repositories.retention import PurgeTargets, purge

    alembic(database, "upgrade", "head")
    [news_id] = save(database, [row()]).ids
    in_session(database, lambda s: purge(s, PurgeTargets(news=[news_id]), reason="보관 정책"))

    result = save(database, [row(cleaned_text="다시 받은 본문", title="새 제목")])

    assert result.filled == 0
    [news] = stored(database)
    assert (news["body_status"], news["cleaned_text"]) == ("purged", None)
    assert news["title"] == "제목", "원문의 일부라 다시 채우지 않는다"


def test_known_news_keys_match_by_canonical_or_original_address(database):
    from app.repositories.news import known_news_keys

    alembic(database, "upgrade", "head")
    save(database, [row("https://News.Example.com/a/1?utm_source=naver")])

    keys = in_session(database, lambda s: known_news_keys(s, [
        "https://news.example.com/a/1", "https://news.example.com/a/2",
    ]))

    assert keys == {"https://news.example.com/a/1"}
