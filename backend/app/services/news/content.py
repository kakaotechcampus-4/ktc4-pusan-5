"""원문 URL에서 본문을 추출한다.

네이버 API는 제목·요약만 주므로 본문은 원문 사이트에서 직접 가져와야 한다.
JS 로 본문을 그리는 사이트(biz.sbs.co.kr 등)는 실패한다 (SOURCES.md 실측 약 10%).
실패해도 예외를 올리지 않고 (None, 사유) 를 돌려준다. 호출 측이 항목을 보존한다.
"""

import asyncio

import httpx
import trafilatura

from app.services.news.clean import clean_text
from app.services.news.schema import NewsItem

_UA = "Mozilla/5.0 (compatible; BASIS-news-collector/0.1)"
_MIN_CHARS = 100  # 이보다 짧으면 본문이 아니라 상용구만 잡힌 것으로 본다


def _extract(html_text: str, url: str) -> str | None:
    return trafilatura.extract(
        html_text,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )


async def fetch_body(client: httpx.AsyncClient, url: str) -> tuple[str | None, str | None]:
    """(본문, 실패사유). 성공하면 사유는 None."""
    try:
        resp = await client.get(url, headers={"User-Agent": _UA}, follow_redirects=True)
    except httpx.HTTPError as e:
        return None, f"request_failed: {type(e).__name__}"
    if resp.status_code != 200:
        return None, f"http_{resp.status_code}"
    text = await asyncio.to_thread(_extract, resp.text, url)
    if not text or len(text) < _MIN_CHARS:
        return None, "extract_empty"
    return text, None


async def attach_bodies(items: list[NewsItem], *, concurrency: int = 5) -> list[NewsItem]:
    """각 항목에 raw_text 또는 body_error 를 채운다. 원문 URL이 있는 항목만 대상."""
    sem = asyncio.Semaphore(concurrency)

    async def one(client: httpx.AsyncClient, item: NewsItem) -> None:
        async with sem:
            body, err = await fetch_body(client, str(item.url))
        item.raw_text = body
        item.body_error = err
        item.cleaned_text = clean_text(body) if body else None

    async with httpx.AsyncClient(timeout=10) as client:
        await asyncio.gather(*(one(client, it) for it in items))
    return items
