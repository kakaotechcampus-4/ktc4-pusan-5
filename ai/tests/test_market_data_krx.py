"""KRX 클라이언트. MockTransport 로 KRX 서버 없이 돈다. 응답은 tests/fixtures/market_data/ 다."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.core.config import settings
from app.services.market_data import (
    KrxAuthError,
    KrxError,
    ParseError,
    compute_excess,
    fetch_kospi,
    fetch_kospi_index_daily,
    fetch_stock,
    fetch_stock_daily,
)

FIXTURES = Path(__file__).parent / "fixtures" / "market_data"
DAY = date(2026, 10, 27)  # fixture 는 이날의 실제 응답이다


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serve(name: str, status: int = 200):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=fixture(name))

    return handler


@pytest.fixture(autouse=True)
def krx_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "krx_auth_key", "test-krx-key")
    return "test-krx-key"


async def test_request_follows_krx_contract() -> None:
    """POST + AUTH_KEY 헤더 + JSON 본문. Content-Type 이 빠지면 KRX 는 항상 빈 배열을 준다."""
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=fixture("krx_kospi_dd_trd.json"))

    async with _client(handler) as client:
        await fetch_kospi(client, DAY)

    [request] = seen
    assert request.method == "POST"
    assert str(request.url) == "https://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd"
    assert request.headers["AUTH_KEY"] == "test-krx-key"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {"basDd": "20261027"}


async def test_kospi_picks_composite_row_with_numbers() -> None:
    async with _client(_serve("krx_kospi_dd_trd.json")) as client:
        kospi = await fetch_kospi(client, DAY)

    assert kospi is not None
    assert kospi.name == "코스피"  # "코스피 (외국주포함)" 행이 아니다
    assert kospi.bas_dd == DAY
    assert kospi.close == 5638.34
    assert kospi.change == 168.87
    assert kospi.change_rate == 3.09
    assert kospi.trade_value == 16416359815240
    assert kospi.market_cap == 4654473109127871


async def test_index_rows_keep_blank_prices_as_none() -> None:
    async with _client(_serve("krx_kospi_dd_trd.json")) as client:
        rows = await fetch_kospi_index_daily(client, DAY)

    assert [r.name for r in rows] == [
        "코스피 (외국주포함)", "코스피", "전기전자", "코스피 200 25/50 NTR 지수"]
    foreign, _, electronics, ntr = rows
    assert foreign.close is None and foreign.change_rate is None
    assert foreign.volume == 196172034
    # 1000 이 넘는 전일대비는 쉼표가 붙어 온다("3,868.34"). 다른 칸은 붙지 않았다
    assert electronics.change == 3868.34
    assert electronics.close == 90296.15
    # NTR 지수는 거래량·거래대금·시가총액 칸이 비어 온다
    assert ntr.change_rate == 3.06
    assert ntr.volume is None and ntr.trade_value is None and ntr.market_cap is None


async def test_stock_row_numbers() -> None:
    async with _client(_serve("krx_stk_bydd_trd.json")) as client:
        stock = await fetch_stock(client, DAY, "095570")

    assert stock is not None
    assert stock.name == "AJ네트웍스"
    assert stock.close == 4010
    assert stock.change == 30
    assert stock.change_rate == 0.75
    assert stock.volume == 73450  # 주 단위
    assert stock.trade_value == 294179909  # 원 단위
    assert stock.market_cap == 181463563590
    assert stock.market_cap == stock.listed_shares * stock.close  # 조사 문서에서 확인한 관계


async def test_no_trade_day_has_no_open_high_low() -> None:
    """DH오토넥스 2026-10-27(거래량 0). 시가·고가·저가 "0" 은 가격이 아니다."""
    async with _client(_serve("krx_stk_bydd_trd.json")) as client:
        stock = await fetch_stock(client, DAY, "000300")

    assert stock is not None
    assert stock.no_trades
    assert (stock.open, stock.high, stock.low) == (None, None, None)
    assert stock.close == 4200  # 직전 가격 그대로 온다
    assert stock.volume == 0 and stock.change_rate == 0.0


async def test_traded_stock_keeps_open_high_low() -> None:
    async with _client(_serve("krx_stk_bydd_trd.json")) as client:
        stock = await fetch_stock(client, DAY, "005930")

    assert not stock.no_trades
    assert (stock.open, stock.high, stock.low) == (222000, 225500, 220000)


async def test_excess_from_real_rows() -> None:
    """2026-10-27 실제 응답: 삼성전자 +4.23%, 코스피 +3.09% → 시장보다 1.14%p 더 올랐다."""
    async with _client(_serve("krx_kospi_dd_trd.json")) as client:
        kospi = await fetch_kospi(client, DAY)
    async with _client(_serve("krx_stk_bydd_trd.json")) as client:
        stock = await fetch_stock(client, DAY, "005930")

    move = compute_excess(stock, kospi)
    assert (move.stock_change_rate, move.index_change_rate, move.excess_rate) == (4.23, 3.09, 1.14)


async def test_no_excess_for_no_trade_stock() -> None:
    """거래정지 종목 등락률 0.00 을 그대로 빼면 −3.09%p 가 된다. 계산하지 않는다."""
    async with _client(_serve("krx_kospi_dd_trd.json")) as client:
        kospi = await fetch_kospi(client, DAY)
    async with _client(_serve("krx_stk_bydd_trd.json")) as client:
        stock = await fetch_stock(client, DAY, "000300")

    assert compute_excess(stock, kospi) is None


async def test_stock_not_listed_is_none() -> None:
    async with _client(_serve("krx_stk_bydd_trd.json")) as client:
        assert await fetch_stock(client, DAY, "999999") is None


async def test_day_without_data_returns_empty(caplog: pytest.LogCaptureFixture) -> None:
    """당일·휴장일은 200 + 빈 배열이다. 에러로 죽지 않고 빈 결과를 준다."""
    async with _client(_serve("krx_empty.json")) as client:
        with caplog.at_level("INFO", logger="app.services.market_data.krx"):
            assert await fetch_kospi(client, DAY) is None
            assert await fetch_kospi_index_daily(client, DAY) == []
            assert await fetch_stock_daily(client, DAY) == []
            assert await fetch_stock(client, DAY, "005930") is None

    assert "데이터 없음" in caplog.text


async def test_string_date_is_rejected_before_request() -> None:
    """문자열 날짜를 보내면 KRX 는 빈 배열을 준다. 휴장일로 오인하지 않게 보내기 전에 막는다."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("요청이 나가면 안 된다")

    async with _client(handler) as client:
        with pytest.raises(TypeError):
            await fetch_kospi(client, "2026-09-10")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "expected"),
    [("krx_unauthorized_key.json", "인증키가 틀렸다"),
     ("krx_unauthorized_api.json", "이용신청")],
)
async def test_401_tells_bad_key_from_unapproved_api(name: str, expected: str) -> None:
    async with _client(_serve(name, status=401)) as client:
        with pytest.raises(KrxAuthError, match=expected):
            await fetch_kospi(client, DAY)


async def test_unexpected_body_is_an_error_not_empty() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"something": "else"})

    async with _client(handler) as client:
        with pytest.raises(KrxError, match="OutBlock_1"):
            await fetch_kospi(client, DAY)


async def test_server_error_is_krx_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    async with _client(handler) as client:
        with pytest.raises(KrxError, match="503"):
            await fetch_stock_daily(client, DAY)


async def test_unreadable_number_stops() -> None:
    body = fixture("krx_stk_bydd_trd.json")
    body["OutBlock_1"][0]["FLUC_RT"] = "N/A"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    async with _client(handler) as client:
        with pytest.raises(ParseError, match="FLUC_RT"):
            await fetch_stock_daily(client, DAY)


def _serve_body(body: dict):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    return handler


def _break_field(row: dict, field: str, how: str) -> None:
    if how == "missing":
        del row[field]
    else:
        row[field] = how


@pytest.mark.parametrize("how", ["missing", "", "  "])
async def test_stock_row_without_code_is_error(how: str) -> None:
    """KRX 가 필드명을 바꾸면 ISU_CD 가 빠진다. 빈 코드로 넘기면 "종목 없음" 으로 보인다."""
    body = fixture("krx_stk_bydd_trd.json")
    _break_field(body["OutBlock_1"][0], "ISU_CD", how)

    async with _client(_serve_body(body)) as client:
        with pytest.raises(KrxError, match="ISU_CD"):
            await fetch_stock_daily(client, DAY)


@pytest.mark.parametrize("how", ["missing", "", "  "])
async def test_index_row_without_name_is_error(how: str) -> None:
    body = fixture("krx_kospi_dd_trd.json")
    _break_field(body["OutBlock_1"][0], "IDX_NM", how)

    async with _client(_serve_body(body)) as client:
        with pytest.raises(KrxError, match="IDX_NM"):
            await fetch_kospi_index_daily(client, DAY)


async def test_missing_key_stops_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "krx_auth_key", None)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("요청이 나가면 안 된다")

    async with _client(handler) as client:
        with pytest.raises(RuntimeError, match="KRX_AUTH_KEY"):
            await fetch_kospi(client, DAY)
