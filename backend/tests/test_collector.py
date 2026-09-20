from datetime import UTC, datetime

from app.collectors.news import _to_row
from app.services.news import NewsItem


def test_to_row_matches_news_columns():
    item = NewsItem(
        title="t",
        url="https://example.com/a",
        publisher="example.com",
        published_at=datetime(2026, 9, 12, tzinfo=UTC),
        source="naver",
    )
    row = _to_row(item)
    assert row["url"] == "https://example.com/a"
    assert set(row) == {
        "url", "title", "publisher", "source", "published_at", "summary", "cleaned_text"
    }
