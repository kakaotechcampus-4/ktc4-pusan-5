"""원문 URL에서 본문을 추출한다.

네이버 API는 제목·요약만 주므로 본문은 원문 사이트에서 직접 가져와야 한다.
JS 로 본문을 그리는 사이트(biz.sbs.co.kr 등)는 실패한다 (SOURCES.md 실측 약 10%).
실패해도 예외를 올리지 않고 (None, 사유) 를 돌려준다. 호출 측이 항목을 보존한다.

본문 추출은 trafilatura를 유지한다. 외부 요청의 주소 검사·리다이렉트·크기 제한은
텔레그램 경로와 공유한다. DNS 재바인딩 한계는 news_link/fetch.py에 설명돼 있다.
"""

import asyncio
from datetime import UTC, datetime

import httpx
import trafilatura

from app.services.news.clean import clean_text
from app.services.news.schema import NewsItem
from app.services.news_link.fetch import (
    BlockedAddressError,
    HtmlTooLargeError,
    decode_html,
    open_public,
    read_limited_html,
)

_MIN_CHARS = 100  # 이보다 짧으면 본문이 아니라 상용구만 잡힌 것으로 본다
BODY_TIMEOUT_SEC = 15.0  # DNS·리다이렉트·본문 수신을 합친 전체 제한


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
        async with asyncio.timeout(BODY_TIMEOUT_SEC), open_public(client, url) as resp:
            if resp.status_code != 200:
                return None, f"http_{resp.status_code}"
            content_type = resp.headers.get("content-type", "")
            if content_type and content_type.split(";", 1)[0].strip().lower() not in (
                "text/html", "application/xhtml+xml",
            ):
                return None, "not_html"
            content = await read_limited_html(resp)
            final_url = str(resp.url)
    except BlockedAddressError:
        return None, "blocked_address"
    except HtmlTooLargeError:
        return None, "too_large"
    except (httpx.HTTPError, TimeoutError) as e:
        return None, f"request_failed: {type(e).__name__}"
    except (OSError, ValueError):
        return None, "request_failed: invalid_address"
    try:
        text = await asyncio.to_thread(_extract, decode_html(content, content_type), final_url)
    except Exception as exc:  # noqa: BLE001 — 한 기사의 실패가 수집 묶음을 중단하지 않게 한다.
        return None, f"extract_failed: {type(exc).__name__}"
    if not text or len(text) < _MIN_CHARS:
        return None, "extract_empty"
    return text, None


async def attach_bodies(items: list[NewsItem], *, concurrency: int = 5) -> list[NewsItem]:
    """각 항목에 raw_text 또는 body_error 를 채운다. 원문 URL이 있는 항목만 대상."""
    sem = asyncio.Semaphore(concurrency)

    async def one(client: httpx.AsyncClient, item: NewsItem) -> None:
        async with sem:
            body, err = await fetch_body(client, str(item.url))
        item.body_fetched_at = datetime.now(UTC)
        item.raw_text = body
        item.body_error = err
        item.cleaned_text = clean_text(body) if body else None

    async with httpx.AsyncClient(timeout=10) as client:
        await asyncio.gather(*(one(client, it) for it in items))
    return items
