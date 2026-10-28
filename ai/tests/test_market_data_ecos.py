"""ECOS 클라이언트. MockTransport 로 한국은행 서버 없이 돈다.

키가 요청 주소에 들어가는 API 라서, 값보다 **키가 새지 않는 것**을 더 꼼꼼히 본다.
"""

import json
import logging
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.services.market_data import (
    BASE_RATE,
    EcosError,
    EcosSeries,
    ecos,
    fetch_base_rate,
    fetch_series,
    fetch_usd_krw,
    mask_key,
)

FIXTURES = Path(__file__).parent / "fixtures" / "market_data"
KEY = "SECRETECOSKEY123"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serve(name: str):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture(name))

    return handler


@pytest.fixture(autouse=True)
def ecos_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "ecos_api_key", KEY)
    return KEY


async def test_usd_krw_request_path_and_values() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=fixture("ecos_usd_krw.json"))

    async with _client(handler) as client:
        points = await fetch_usd_krw(client, date(2026, 9, 8), date(2026, 9, 10))

    [request] = seen
    assert request.method == "GET"
    assert str(request.url) == (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/1000/"
        "731Y001/D/20260908/20260910/0000001"
    )
    assert [p.value for p in points] == [1388.5, 1391.2, 1385.2]  # 쉼표 섞인 값도 읽는다
    assert [p.period_start for p in points] == [date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)]
    assert points[0].unit == "원"
    assert points[0].item_name == "원/미국달러(매매기준율)"


async def test_base_rate_is_monthly() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=fixture("ecos_base_rate.json"))

    async with _client(handler) as client:
        points = await fetch_base_rate(client, date(2026, 8, 15), date(2026, 9, 30))

    assert seen[0].endswith("/722Y001/M/202608/202609/0101000"), "월 주기는 YYYYMM 으로 보낸다"
    assert [(p.time, p.period_start, p.value) for p in points] == [
        ("202608", date(2026, 8, 1), 2.5),
        ("202609", date(2026, 9, 1), 2.25),
    ]
    assert points[0].unit == "연%"


async def test_no_data_is_empty_not_error() -> None:
    async with _client(_serve("ecos_no_data.json")) as client:
        assert await fetch_usd_krw(client, date(2026, 9, 12), date(2026, 9, 13)) == []


async def test_long_range_is_fetched_page_by_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ecos, "PAGE_SIZE", 2)
    rows = fixture("ecos_usd_krw.json")["StatisticSearch"]["row"]
    ranges: list[tuple[int, int]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        first, last = (int(x) for x in request.url.path.split("/")[6:8])
        ranges.append((first, last))
        page = rows[first - 1:last]
        return httpx.Response(200, json={"StatisticSearch": {"list_total_count": 3, "row": page}})

    async with _client(handler) as client:
        points = await fetch_usd_krw(client, date(2026, 9, 8), date(2026, 9, 10))

    assert ranges == [(1, 2), (3, 4)]
    assert len(points) == 3


async def test_result_error_is_masked() -> None:
    async with _client(_serve("ecos_invalid_key.json")) as client:
        with pytest.raises(EcosError, match="INFO-100") as caught:
            await fetch_usd_krw(client, date(2026, 9, 8), date(2026, 9, 10))

    assert KEY not in str(caught.value)
    assert "/***/" in str(caught.value)


async def test_http_status_error_is_masked() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="error")

    async with _client(handler) as client:
        with pytest.raises(EcosError, match="500") as caught:
            await fetch_usd_krw(client, date(2026, 9, 8), date(2026, 9, 10))

    _assert_no_key_anywhere(caught.value)


async def test_transport_error_does_not_carry_url() -> None:
    """httpx 예외는 request(원래 주소)를 들고 있다. 연결해서 올리면 traceback 에 키가 남는다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection refused for {request.url}", request=request)

    async with _client(handler) as client:
        with pytest.raises(EcosError) as caught:
            await fetch_usd_krw(client, date(2026, 9, 8), date(2026, 9, 10))

    _assert_no_key_anywhere(caught.value)


async def test_httpx_request_log_is_masked(caplog: pytest.LogCaptureFixture) -> None:
    """httpx 는 INFO 로 "HTTP Request: GET <주소>" 를 남긴다. 그 주소의 키를 가린다."""
    async with _client(_serve("ecos_usd_krw.json")) as client:
        with caplog.at_level(logging.INFO, logger="httpx"):
            await fetch_usd_krw(client, date(2026, 9, 8), date(2026, 9, 10))

    assert "StatisticSearch/***/json" in caplog.text
    assert KEY not in caplog.text


def test_mask_key() -> None:
    assert mask_key(f"https://x/{KEY}/json", KEY) == "https://x/***/json"
    assert mask_key("nothing", None) == "nothing"
    assert mask_key("nothing", "") == "nothing"


async def test_unsupported_cycle_and_reversed_range() -> None:
    async with _client(_serve("ecos_usd_krw.json")) as client:
        with pytest.raises(ValueError, match="주기"):
            await fetch_series(client, EcosSeries("722Y001", "Q", "0101000", "분기"),
                               date(2026, 1, 1), date(2026, 9, 30))
        with pytest.raises(ValueError, match="늦다"):
            await fetch_series(client, BASE_RATE, date(2026, 9, 30), date(2026, 1, 1))


async def test_missing_key_stops_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ecos_api_key", "")

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("요청이 나가면 안 된다")

    async with _client(handler) as client:
        with pytest.raises(RuntimeError, match="ECOS_API_KEY"):
            await fetch_usd_krw(client, date(2026, 9, 8), date(2026, 9, 10))


def _assert_no_key_anywhere(error: BaseException) -> None:
    assert KEY not in str(error)
    assert error.__cause__ is None
    # httpx 예외를 받아 다시 던졌다면 from None 이어야 traceback 에 원래 예외(주소)가 안 찍힌다
    assert error.__context__ is None or error.__suppress_context__
