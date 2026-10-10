"""네이버 뉴스 수집기의 행 변환. backend tests/test_collector.py 에서 옮겨 왔다."""

from datetime import UTC, datetime

from app.collectors.news import _to_row
from app.models import News
from app.services.news import NewsItem


def _item(**values) -> NewsItem:
    return NewsItem(**{
        "title": "t",
        "url": "https://example.com/a",
        "publisher": "example.com",
        "published_at": datetime(2026, 9, 12, tzinfo=UTC),
        "source": "naver",
        **values,
    })


def test_to_row_matches_news_columns():
    row = _to_row(_item())
    assert row["url"] == "https://example.com/a"
    assert set(row) <= set(News.__table__.columns.keys())
    assert set(row) == {
        "url", "title", "publisher", "source", "published_at", "summary", "cleaned_text",
        "body_status", "body_error", "body_fetched_at", "body_extractor",
    }


def test_to_row_marks_extracted_body_as_ok():
    fetched = datetime(2026, 9, 12, 1, tzinfo=UTC)
    row = _to_row(_item(cleaned_text="본문", body_fetched_at=fetched))
    assert (row["body_status"], row["body_error"], row["cleaned_text"]) == ("ok", None, "본문")
    assert row["body_fetched_at"] == fetched
    assert row["body_extractor"] == "trafilatura"


def test_to_row_keeps_failure_reason_and_does_not_store_an_empty_body():
    assert _to_row(_item(body_error="http_404"))[
        "body_status"] == "failed"
    assert _to_row(_item(body_error="http_404"))["body_error"] == "http_404"
    # 원문은 받았지만 정제하고 나니 남은 게 없다
    empty = _to_row(_item(raw_text="ⓒ 무단 전재", cleaned_text=""))
    assert (empty["body_status"], empty["body_error"], empty["cleaned_text"]) == (
        "failed", "clean_empty", None)


# ── 수집 범위 ─────────────────────────────────────────────

def _scope(**naver_news):
    from datetime import date

    from app.core.scope import parse_scope

    return parse_scope({
        "period": {"start": date(2026, 9, 10), "end": date(2026, 9, 30)},
        "sources": {"naver_news": {"enabled": True, "queries": ["삼성전자"], "max_items": 2,
                                   "terms": {"status": "미확인"}, **naver_news}},
    })


def test_select_items_keeps_known_articles_and_new_ones_up_to_the_limit():
    from app.collectors.news import CollectResult, select_items

    scope = _scope()
    items = [
        _item(url="https://example.com/known"),
        _item(url="https://example.com/old", published_at=datetime(2026, 9, 1, tzinfo=UTC)),
        _item(url="https://example.com/new1"),
        _item(url="https://example.com/new1?utm_source=naver"),  # 같은 기사 — 한 번만 센다
        _item(url="https://example.com/new2"),
    ]
    result = CollectResult()

    kept = select_items(items, scope=scope, source=scope.require("naver_news"),
                        known={"https://example.com/known"}, collected=1, result=result)

    assert [str(i.url) for i in kept] == [
        "https://example.com/known",
        "https://example.com/new1",
        "https://example.com/new1?utm_source=naver",
    ]
    assert (result.out_of_period, result.held) == (1, 1)


async def test_query_outside_the_scope_is_refused_before_searching(monkeypatch):
    import pytest

    from app.collectors import news as collector
    from app.core.scope import ScopeError

    monkeypatch.setattr(collector.naver, "search", lambda *a, **k: pytest.fail("검색했다"))
    with pytest.raises(ScopeError, match="SK하이닉스"):
        await collector.collect("SK하이닉스", scope=_scope())
