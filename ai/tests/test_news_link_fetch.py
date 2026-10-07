"""링크 열기. httpx MockTransport 로 남의 서버 없이 돈다.

여기서 지키려는 것은 **실패해도 건질 것은 건진다**는 성질이다. 링크 하나가
죽었다고 예외를 올리면 그날치 수집이 통째로 멈춘다.
"""

import gzip
import socket
from collections.abc import AsyncIterator

import httpx
import pytest

from app.services.news_link import fetch
from app.services.news_link.fetch import (
    MAX_HTML_BYTES,
    MAX_REDIRECTS,
    fetch_link,
    fetch_link_bodies,
    is_fetchable,
    is_public_ip,
)

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


async def test_excerpt_is_the_head_of_the_article_body() -> None:
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


async def test_whole_body_text_is_kept_for_storage_but_not_serialized() -> None:
    """news 에 저장하는 것은 발췌가 아니라 정제한 본문 전체다. 파일·로그로는 나가지 않는다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/news/1", sentences=1)

    assert body.excerpt == "삼성전자가 차세대 메모리 기술을 공개했다고 밝혔다."
    assert body.text == (
        "삼성전자가 차세대 메모리 기술을 공개했다고 밝혔다.\n"
        "회사는 내년 하반기 양산을 목표로 하고 있다고 이날 설명했다.\n"
        "업계는 공급 확대가 가격에 영향을 줄 것으로 보고 있다고 전했다."
    ), "바이라인·저작권 안내는 정제된 뒤다"
    assert body.excerpt and body.text.startswith(body.excerpt) and body.text != body.excerpt
    assert "text" not in body.model_dump()
    assert "회사는" not in repr(body)


async def test_shortened_url_resolves_to_its_final_address() -> None:
    """본문을 못 읽어도 이게 이 기능의 1번 값어치다. 모델이 출처를 알아본다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "buly.kr":
            return httpx.Response(302, headers={"location": "https://www.ytn.co.kr/_ln/0104"})
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://buly.kr/DPWhsGM")

    assert body.final_url == "https://www.ytn.co.kr/_ln/0104"
    assert body.domain == "www.ytn.co.kr"


async def test_pdf_keeps_only_the_domain() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    async with _client(handler) as client:
        body = await fetch_link(client, "https://file.hanaw.com/report.pdf")

    assert body.status == "pdf"
    assert body.domain == "file.hanaw.com"
    assert body.excerpt is None


async def test_bot_blocking_site_is_recorded_as_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://www.reuters.com/x")

    assert body.status == "http_error"
    assert body.http_status == 401


async def test_network_failure_does_not_raise() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/dead")

    assert body.status == "error"
    assert body.error is not None and body.error.startswith("ConnectError")


async def test_euc_kr_article_is_not_mojibake() -> None:
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


async def test_missing_body_is_recorded_as_no_body() -> None:
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
def test_ticker_string_is_not_treated_as_a_link(url: str, expected: bool) -> None:
    assert is_fetchable(url) is expected


async def test_duplicate_url_is_fetched_only_once() -> None:
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


async def test_result_length_may_differ_from_input() -> None:
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


# ── 공개 인터넷 주소만 연다 (SSRF) ─────────────────────────────────
# 주소는 남의 채널이 적은 것이다. 서버가 대신 열어주므로 내부망을 가리키면
# 밖에서 닿지 않는 곳에 우리 서버가 요청을 보내게 된다.


async def test_redirect_to_internal_address_is_not_followed() -> None:
    """처음 주소는 평범한 단축 URL 이어도 302 가 클라우드 메타데이터를 가리킬 수 있다."""
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})

    async with _client(handler) as client:
        body = await fetch_link(client, "https://buly.kr/abc")

    assert body.status == "blocked"
    assert calls == ["https://buly.kr/abc"], "내부 주소로는 요청이 나가지 않는다"
    # 막힌 목적지는 조사용으로 error 에만 남는다. final_url·domain 은 "실제로 도착한 곳" 이다
    assert body.error is not None and "169.254.169.254" in body.error
    assert body.final_url is None
    assert body.domain is None


async def test_internal_address_written_in_the_message_is_not_opened() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "http://127.0.0.1:8000/admin")

    assert body.status == "blocked"
    assert calls == []


async def test_domain_pointing_to_internal_ip_is_blocked(fake_dns: dict[str, list[str]]) -> None:
    """이름만 보면 모른다. evil.example 이 127.0.0.1 을 가리키게 둘 수 있다."""
    fake_dns["evil.example"] = ["127.0.0.1"]
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://evil.example/news")

    assert body.status == "blocked"
    assert calls == []


async def test_domain_is_blocked_if_any_of_its_ips_is_internal(
    fake_dns: dict[str, list[str]],
) -> None:
    fake_dns["mixed.example"] = ["93.184.216.34", "10.0.0.5"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://mixed.example/news")

    assert body.status == "blocked"


async def test_domain_with_no_ip_is_blocked(fake_dns: dict[str, list[str]]) -> None:
    """IP 를 하나도 못 받으면 검사할 것이 없다. "전부 공개" 로 치고 통과시키지 않는다."""
    fake_dns["empty.example"] = []
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://empty.example/news")

    assert body.status == "blocked"
    assert calls == []


async def test_dns_failure_is_an_error_and_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """없는 도메인은 막은 게 아니라 못 연 것이다. 어느 쪽이든 요청은 나가지 않는다."""

    async def resolve(host: str) -> list[str]:
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(fetch, "resolve_host", resolve)
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://no-such-host.example/x")

    assert body.status == "error"
    assert body.error is not None and body.error.startswith("gaierror")
    assert calls == []


async def test_relative_redirect_is_resolved_against_the_current_address() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/short":
            return httpx.Response(301, headers={"location": "/news/1"})
        return httpx.Response(200, html=ARTICLE_HTML)

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/short")

    assert body.status == "ok"
    assert body.final_url == "https://example.com/news/1"


async def test_redirect_loop_stops() -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": f"https://example.com/{len(calls)}"})

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/0")

    assert body.status == "error"
    assert body.error is not None and body.error.startswith("TooManyRedirects")
    assert len(calls) == MAX_REDIRECTS + 1


async def test_client_that_follows_redirects_itself_is_still_checked() -> None:
    """수집기가 follow_redirects=True 로 만든 client 를 넘겨도 검사를 건너뛰지 않는다."""
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "buly.kr":
            return httpx.Response(302, headers={"location": "http://10.0.0.5/"})
        return httpx.Response(200, html=ARTICLE_HTML)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        body = await fetch_link(client, "https://buly.kr/abc")

    assert body.status == "blocked"
    assert calls == ["https://buly.kr/abc"]


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("8.8.8.8", True),
        ("2001:4860:4860::8888", True),
        ("127.0.0.1", False),  # 자기 자신
        ("10.0.0.5", False),  # 사설망
        ("192.168.0.1", False),
        ("169.254.169.254", False),  # 클라우드 메타데이터
        ("100.64.0.1", False),  # 통신사·클라우드 내부망. is_private 로는 안 걸린다
        ("0.0.0.0", False),
        ("224.0.0.1", False),  # 멀티캐스트. is_global 은 True 다
        ("::1", False),
        ("::ffff:127.0.0.1", False),  # IPv6 에 실은 IPv4 루프백
        ("fe80::1%eth0", False),  # 링크 로컬. 꼬리(%eth0)가 붙어 온다
    ],
)
def test_only_public_internet_addresses_pass(address: str, expected: bool) -> None:
    assert is_public_ip(address) is expected


# ── 본문 크기 상한 ──────────────────────────────────────────────
# 상한은 메모리를 지키려는 것이다. 판정 결과(too_large)만 맞아서는 안 되고,
# 넘는 순간 받기를 멈춰야 한다. 끝없이 보내는 서버 하나에 수집기가 통째로 죽으면 안 된다.

CHUNK_BYTES = 64 * 1024


def _counted_chunks(count: int, sent: list[int], chunk: bytes = b"a" * CHUNK_BYTES):
    """조각을 하나 내보낼 때마다 sent 에 적는다. 몇 개나 받아 갔는지로 멈춘 시점을 본다."""

    async def stream() -> AsyncIterator[bytes]:
        for _ in range(count):
            sent.append(len(chunk))
            yield chunk

    return stream()


async def test_body_without_content_length_stops_as_soon_as_it_exceeds_the_limit() -> None:
    """content-length 가 없으면 헤더로는 못 거른다. 다 받고 나서 재면 이미 늦다."""
    sent: list[int] = []
    total_chunks = 200  # 12.8MB. 상한(3MB)의 네 배쯤

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=_counted_chunks(total_chunks, sent),
        )

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/endless")

    assert body.status == "too_large"
    # 상한을 넘긴 조각(46번째)까지만 받는다. 끝까지 받았다면 200개다.
    # httpx 가 한두 조각 미리 당겨 올 수 있어서 한 칸 여유를 둔다.
    assert len(sent) <= MAX_HTML_BYTES // CHUNK_BYTES + 2


async def test_compressed_body_is_measured_after_decompression() -> None:
    """content-length 는 압축된 크기라 작게 보인다. 메모리에는 푼 크기가 올라간다."""
    raw = b"<html><body>" + b"a" * (MAX_HTML_BYTES * 3) + b"</body></html>"
    compressed = gzip.compress(raw)
    assert len(compressed) < MAX_HTML_BYTES, "헤더 검사를 통과하는 크기여야 의미가 있다"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-encoding": "gzip"},
            content=compressed,  # content-length 는 압축된 크기로 붙는다
        )

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/bomb")

    assert body.status == "too_large"


async def test_honest_content_length_over_the_limit_reads_no_body() -> None:
    """크기를 정직하게 알려주면 본문을 한 조각도 받지 않고 끊는다."""
    sent: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html", "content-length": str(MAX_HTML_BYTES * 10)},
            content=_counted_chunks(10, sent),
        )

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/huge")

    assert body.status == "too_large"
    assert sent == []


async def test_article_split_into_small_chunks_is_reassembled_intact() -> None:
    """조각을 이어 붙이다 깨지면 안 된다. 한글이 조각 경계에서 잘려도 마찬가지다."""
    data = ARTICLE_HTML.encode("utf-8")

    async def stream() -> AsyncIterator[bytes]:
        for i in range(0, len(data), 7):  # 7바이트씩. 한글(3바이트)이 경계에서 잘린다
            yield data[i : i + 7]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=stream()
        )

    async with _client(handler) as client:
        body = await fetch_link(client, "https://example.com/news/chunked")

    assert body.status == "ok"
    assert body.excerpt is not None
    assert body.excerpt.startswith("삼성전자가 차세대 메모리 기술을 공개했다고 밝혔다.")
