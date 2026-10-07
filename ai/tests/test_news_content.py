"""backend tests/test_content.py 에서 옮겨 왔다. 뉴스 수집은 이제 ai/ 가 맡는다."""

import httpx
import pytest
import respx

from app.services.news.content import fetch_body
from app.services.news_link.fetch import MAX_HTML_BYTES


@respx.mock
async def test_fetch_body_reports_http_error_without_raising():
    respx.get("https://example.com/gone").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        body, err = await fetch_body(client, "https://example.com/gone")
    assert body is None
    assert err == "http_404"


@respx.mock
async def test_fetch_body_treats_short_page_as_empty():
    respx.get("https://example.com/short").mock(
        return_value=httpx.Response(200, text="<html><body><p>짧다</p></body></html>",
                                   headers={"content-type": "text/html; charset=utf-8"})
    )
    async with httpx.AsyncClient() as client:
        body, err = await fetch_body(client, "https://example.com/short")
    assert body is None
    assert err == "extract_empty"


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/private", "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/", "file:///etc/passwd", "https://internal.example.com/",
])
async def test_private_targets_are_rejected_before_http(url, fake_dns):
    fake_dns["internal.example.com"] = ["10.0.0.1"]

    def mock_handler(request):
        pytest.fail("A blocked address reached the HTTP transport")

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        assert await fetch_body(client, url) == (None, "blocked_address")


async def test_redirect_to_private_address_is_rejected_even_with_auto_redirects():
    mock_opened = []

    def mock_handler(request):
        mock_opened.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(mock_handler), follow_redirects=True,
    ) as client:
        assert await fetch_body(client, "https://example.com/news") == (None, "blocked_address")
    assert mock_opened == ["https://example.com/news"]


@pytest.mark.parametrize("declared", [True, False])
async def test_oversized_html_is_rejected_with_or_without_content_length(declared):
    class MockStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(4):
                yield b"x" * 1_000_000

    mock_headers = {"content-type": "text/html"}
    if declared:
        mock_headers["content-length"] = str(MAX_HTML_BYTES + 1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, headers=mock_headers, stream=MockStream()),
    )) as client:
        assert await fetch_body(client, "https://example.com/news") == (None, "too_large")


async def test_extraction_failure_does_not_abort_the_batch(monkeypatch):
    from app.services.news import content

    def mock_extract(*args):
        raise RuntimeError("mock parser failure")

    monkeypatch.setattr(content, "_extract", mock_extract)
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, html="<article>mock</article>"),
    )) as client:
        assert await fetch_body(client, "https://example.com/news") == (
            None, "extract_failed: RuntimeError",
        )


async def test_total_timeout_includes_dns(monkeypatch):
    import asyncio

    from app.services.news import content
    from app.services.news_link import fetch

    async def mock_resolve(host):
        await asyncio.Event().wait()

    monkeypatch.setattr(content, "BODY_TIMEOUT_SEC", 0.02)
    monkeypatch.setattr(fetch, "resolve_host", mock_resolve)
    async with httpx.AsyncClient() as client:
        assert await fetch_body(client, "https://example.com/news") == (
            None, "request_failed: TimeoutError",
        )
