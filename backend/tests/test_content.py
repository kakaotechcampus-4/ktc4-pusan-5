import httpx
import respx

from app.services.news.content import fetch_body


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
        return_value=httpx.Response(200, text="<html><body><p>짧다</p></body></html>")
    )
    async with httpx.AsyncClient() as client:
        body, err = await fetch_body(client, "https://example.com/short")
    assert body is None
    assert err == "extract_empty"
