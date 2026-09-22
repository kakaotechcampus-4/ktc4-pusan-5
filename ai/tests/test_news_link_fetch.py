"""링크 열기. httpx MockTransport 로 남의 서버 없이 돈다.

여기서 지키려는 것은 **실패해도 건질 것은 건진다**는 성질이다. 링크 하나가
죽었다고 예외를 올리면 그날치 수집이 통째로 멈춘다.
"""

import httpx
import pytest

from app.services.news_link.fetch import fetch_link, fetch_link_bodies, is_fetchable

ARTICLE_HTML = """
<html><head><meta property="og:title" content="삼성전자 zHBM 공개"></head>
<body><article>
<p>(서울=연합뉴스) 이도흔 기자 = 삼성전자가 차세대 메모리 기술을 공개했다고 밝혔다.</p>
<p>회사는 내년 하반기 양산을 목표로 하고 있다고 이날 설명했다.</p>
<p>업계는 공급 확대가 가격에 영향을 줄 것으로 보고 있다고 전했다.</p>
<p>ⓒ 무단 전재 및 재배포 금지</p>
</article></body></html>
"""


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_기사를_열면_발췌가_본문의_앞부분이다() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/news/1")

    assert body.status == "ok"
    assert body.title == "삼성전자 zHBM 공개"
    assert body.excerpt is not None
    assert body.excerpt.startswith("삼성전자가 차세대 메모리 기술을 공개했다고 밝혔다.")
    assert "무단 전재" not in body.excerpt
    assert body.chars == len(body.excerpt)
    assert body.fetched_at.tzinfo is not None, "naive datetime 을 쓰지 않는다"


async def test_단축_URL_은_최종_주소로_풀린다() -> None:
    """본문을 못 읽어도 이게 이 기능의 1번 값어치다. 모델이 출처를 알아본다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "buly.kr":
            return httpx.Response(302, headers={"location": "https://www.ytn.co.kr/_ln/0104"})
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://buly.kr/DPWhsGM")

    assert body.final_url == "https://www.ytn.co.kr/_ln/0104"
    assert body.domain == "www.ytn.co.kr"


async def test_PDF_는_본문_없이_도메인만_남긴다() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    async with _client(handler) as client:
        body = await fetch_link(client, "https://file.hanaw.com/report.pdf")

    assert body.status == "pdf"
    assert body.domain == "file.hanaw.com"
    assert body.excerpt is None


async def test_봇을_막는_사이트는_http_error_로_남는다() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://www.reuters.com/x")

    assert body.status == "http_error"
    assert body.http_status == 401


async def test_네트워크가_끊겨도_예외를_올리지_않는다() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/dead")

    assert body.status == "error"
    assert body.error is not None and body.error.startswith("ConnectError")


async def test_EUC_KR_기사도_깨지지_않는다() -> None:
    """httpx 는 charset 이 없으면 utf-8 로 읽는다. 국내 매체에는 아직 EUC-KR 이 있다."""
    html = ARTICLE_HTML.replace("<head>", '<head><meta charset="euc-kr">')

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=html.encode("euc-kr"), headers={"content-type": "text/html"}
        )

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.co.kr/news/1")

    assert body.status == "ok"
    assert body.excerpt is not None and "삼성전자" in body.excerpt


async def test_본문을_못_찾으면_no_body_다() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<html><body><div id='app'></div></body></html>")

    async with _client(handler) as client:
        body = await fetch_link(client, "https://biz.sbs.co.kr/article/1")

    assert body.status == "no_body"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://buly.kr/DPWhsGM", True),
        ("https://PLTR.US", False),  # 텔레그램이 티커를 링크로 만든 것
        ("https://Pony.ai/", False),
        ("ftp://example.com/x", False),
    ],
)
def test_티커_문자열은_링크로_보지_않는다(url: str, expected: bool) -> None:
    assert is_fetchable(url) is expected


async def test_같은_링크는_한_번만_연다() -> None:
    """한 채널이 같은 기사를 여러 번 올린다. 중복이어도 결과는 준 순서대로 다시 깔린다."""
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, html=ARTICLE_HTML)

    urls = ["https://example.com/a", "https://example.com/a"]
    async with _client(handler) as client:
        bodies = await fetch_link_bodies(urls, client=client)

    assert len(calls) == 1
    assert [b.url for b in bodies] == urls


async def test_결과는_입력과_길이가_다를_수_있다() -> None:
    """**호출 측이 인덱스로 짝지으면 안 된다는 뜻이다.** url 로 맞춰야 한다.

    열어볼 값어치가 없는 주소(텔레그램이 티커를 링크로 만든 것)는 아예 빠져서
    돌아온다. 수집기를 붙일 때 `zip(urls, bodies)` 를 쓰면 그 뒤로 전부 한 칸씩
    밀린 채 저장된다 — 터지지 않고 조용히 틀린다.
    """

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=ARTICLE_HTML)

    urls = ["https://example.com/a", "https://PLTR.US", "https://example.com/b"]
    async with _client(handler) as client:
        bodies = await fetch_link_bodies(urls, client=client)

    assert [b.url for b in bodies] == ["https://example.com/a", "https://example.com/b"]
