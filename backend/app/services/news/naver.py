"""NAVER API HUB 뉴스 검색 어댑터.

https://naverapihub.apigw.ntruss.com/search/v1/news
응답 필드: title, originallink, link, description, pubDate (RFC 2822)
"""

import html
import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.services.news.schema import NewsItem

NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    """네이버는 검색어를 <b> 태그로 감싸고 HTML 엔티티를 쓴다."""
    return html.unescape(_TAG_RE.sub("", text)).strip()


def _publisher_from(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def parse_items(raw_items: list[dict]) -> list[NewsItem]:
    items: list[NewsItem] = []
    for raw in raw_items:
        url = raw.get("originallink") or raw.get("link")
        if not url:
            continue
        items.append(
            NewsItem(
                title=_clean(raw["title"]),
                url=url,
                publisher=_publisher_from(url),
                published_at=parsedate_to_datetime(raw["pubDate"]),
                source="naver",
                summary=_clean(raw.get("description", "")),
            )
        )
    return items


class NaverNewsError(Exception):
    """네이버 뉴스 검색 실패. 원인 예외는 __cause__ 에 남는다."""


async def search(
    query: str, *, display: int = 20, sort: str = "date"
) -> list[NewsItem]:
    """검색어(보통 종목명)로 뉴스를 가져온다. display 최대 100, sort는 date|sim."""
    headers = {
        "X-NCP-APIGW-API-KEY-ID": settings.naver_client_id,
        "X-NCP-APIGW-API-KEY": settings.naver_client_secret,
    }
    params = {"query": query, "display": display, "sort": sort, "format": "json"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(NAVER_NEWS_URL, headers=headers, params=params)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise NaverNewsError(f"{query}: HTTP {e.response.status_code}") from e
    except httpx.HTTPError as e:
        raise NaverNewsError(f"{query}: {type(e).__name__}") from e
    return parse_items(resp.json().get("items", []))
