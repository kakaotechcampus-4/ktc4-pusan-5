import httpx
import pytest
import respx

from app.services.news import naver
from app.services.news.naver import NAVER_NEWS_URL, parse_items

RAW = {
    "title": "삼성전자, <b>3분기</b> 잠정실적 발표 &amp; 전망",
    "originallink": "https://www.example.com/news/1",
    "link": "https://n.news.naver.com/xxx",
    "description": "요약 <b>텍스트</b>",
    "pubDate": "Fri, 12 Sep 2026 09:30:00 +0900",
}


def test_parse_items_strips_tags_and_picks_original_url():
    [item] = parse_items([RAW])
    assert item.title == "삼성전자, 3분기 잠정실적 발표 & 전망"
    assert str(item.url) == "https://www.example.com/news/1"
    assert item.publisher == "example.com"
    assert item.summary == "요약 텍스트"
    assert item.published_at.utcoffset() is not None
    assert item.source == "naver"


def test_parse_items_skips_entry_without_url():
    assert parse_items([{"title": "x", "pubDate": RAW["pubDate"]}]) == []


@respx.mock
async def test_search_calls_naver_and_returns_items():
    route = respx.get(NAVER_NEWS_URL).mock(
        return_value=httpx.Response(200, json={"items": [RAW]})
    )
    items = await naver.search("삼성전자", display=5)
    assert route.called
    assert route.calls.last.request.url.params["display"] == "5"
    assert len(items) == 1


@respx.mock
async def test_search_wraps_http_error():
    respx.get(NAVER_NEWS_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(naver.NaverNewsError):
        await naver.search("삼성전자")
