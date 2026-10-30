"""입력 market_compare 칸. KRX 를 부르지 않는다(fetch_kospi·fetch_stock_daily 를 바꿔 끼운다).

시장 맥락은 tests/fixtures/market_data/ 의 2026-10-27 실제 응답으로 만든다(test_market_data_context 와 같은 행).
"""

import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.services.market_data import MarketContext, build_market_context
from app.services.market_data.errors import KrxAuthError, KrxError
from app.services.stock_analysis import market_compare as mc
from tests.test_market_data_context import DAY, KOSPI, STOCKS

TARGET_DATE = "2026-10-27"


def payload(code: str = "105560", target_date: str = TARGET_DATE) -> dict:
    return {"code": code, "target_date": target_date}


@pytest.fixture
def krx(monkeypatch):
    """2026-10-27 fixture 응답을 돌려준다. 호출 수를 센다."""
    kospi = AsyncMock(return_value=KOSPI)
    stocks = AsyncMock(return_value=STOCKS)
    monkeypatch.setattr(mc, "fetch_kospi", kospi)
    monkeypatch.setattr(mc, "fetch_stock_daily", stocks)
    return kospi, stocks


def test_kb_follows_prompt_input_format() -> None:
    compare = mc.to_input(build_market_context("105560", DAY, KOSPI, STOCKS))

    assert list(compare) == ["status", "status_reason", "kospi", "peers"]
    assert (compare["status"], compare["status_reason"]) == ("ok", None)
    # 프롬프트 1부의 칸만, 그 순서로. 비중 분모·재계산 코스피·weight_basis 는 보내지 않는다
    assert tuple(compare["kospi"]) == mc.KOSPI_KEYS
    assert compare["kospi"]["kospi_basis"] == "kospi"
    assert compare["kospi"]["excess_vs_kospi_pp"] == -2.82
    assert compare["kospi"]["kospi_relation"] == "diverges"

    [peer] = compare["peers"]
    assert peer["group"] == "은행지주" and peer["relation"] == "follows"
    assert peer["members_used"] == [
        {"code": "055550", "name": "신한지주"}, {"code": "086790", "name": "하나금융지주"},
        {"code": "316140", "name": "우리금융지주"}]
    assert peer["members_excluded"] == [{"code": "105560", "name": "KB금융", "reason": "self"}]
    json.dumps(compare, ensure_ascii=False)  # 모델 입력에 그대로 들어간다


def test_samsung_compares_with_kospi_ex_self() -> None:
    compare = mc.to_input(build_market_context("005930", DAY, KOSPI, STOCKS))
    assert compare["kospi"]["kospi_basis"] == "kospi_ex_self"
    assert compare["kospi"]["excess_vs_kospi_ex_self_pp"] == 2.23
    assert compare["peers"][0]["members_used"] == [{"code": "000660", "name": "SK하이닉스"}]


def test_status_only_context_has_no_kospi() -> None:
    ctx = MarketContext(bas_dd=DAY, code="105560", status="stock_not_found", status_reason="r")
    assert mc.to_input(ctx) == {"status": "stock_not_found", "status_reason": "r", "kospi": None, "peers": []}


async def test_fetches_by_input_date_and_builds_for_input_code(krx) -> None:
    kospi, stocks = krx
    client = object()

    compare, error = await mc.MarketCompare(client)(payload())

    kospi.assert_awaited_once_with(client, DAY)
    stocks.assert_awaited_once_with(client, DAY)
    assert error is None
    assert compare == mc.to_input(build_market_context("105560", DAY, KOSPI, STOCKS))


# --- 기준일마다 한 번 -------------------------------------------------------------------------


async def test_same_day_reuses_krx_responses(krx) -> None:
    """같은 기준일 세 종목이면 KRX 는 코스피·전 종목 한 번씩이다. 종목마다 계산은 따로다."""
    kospi, stocks = krx
    compare_for = mc.MarketCompare(object())

    results = [await compare_for(payload(code)) for code in ("005930", "105560", "000660")]

    assert (kospi.await_count, stocks.await_count) == (1, 1)
    assert [c["kospi"]["kospi_basis"] for c, _ in results] == ["kospi_ex_self", "kospi", "kospi_ex_self"]
    assert [e for _, e in results] == [None, None, None]


async def test_same_day_requests_in_flight_share_one_call(krx) -> None:
    """러너는 보고서를 동시에 돌린다. 첫 응답이 오기 전에 들어온 같은 날 요청도 새로 부르지 않는다."""
    kospi, stocks = krx
    release = asyncio.Event()

    async def slow_kospi(client, day):
        await release.wait()
        return KOSPI

    kospi.side_effect = slow_kospi
    compare_for = mc.MarketCompare(object())
    pending = [asyncio.create_task(compare_for(payload(code))) for code in ("005930", "105560", "000660")]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*pending)

    assert (kospi.await_count, stocks.await_count) == (1, 1)
    assert all(c["status"] == "ok" for c, _ in results)


async def test_each_day_is_fetched_once(krx) -> None:
    kospi, stocks = krx
    compare_for = mc.MarketCompare(object())

    for target_date in (TARGET_DATE, "2026-10-28", TARGET_DATE, "2026-10-28"):
        await compare_for(payload(target_date=target_date))

    assert [c.args[1] for c in kospi.await_args_list] == [DAY, date(2026, 10, 28)]
    assert stocks.await_count == 2


async def test_no_data_day_goes_as_status_only(krx) -> None:
    """기준일 데이터가 없으면 실패가 아니다. status 만 있는 칸이 가고 프롬프트가 비교 문장을 쓰지 않게 한다.
    코스피가 없는 날은 전 종목을 부르지 않고, 같은 날 다른 종목도 다시 부르지 않는다."""
    kospi, stocks = krx
    kospi.return_value = None
    compare_for = mc.MarketCompare(object())

    first, error = await compare_for(payload("105560"))
    second, _ = await compare_for(payload("005930"))

    assert error is None
    assert first["status"] == "no_data" and "데이터가 없다" in first["status_reason"]
    assert first["kospi"] is None and first["peers"] == []
    assert second["status"] == "no_data"
    assert (kospi.await_count, stocks.await_count) == (1, 0)


# --- 실패 -------------------------------------------------------------------------------------


@pytest.mark.parametrize("exc", [
    KrxError("KRX stk_bydd_trd 20261027 요청 실패: ConnectTimeout: "),
    KrxAuthError("KRX: 인증키가 틀렸다"),
    RuntimeError("KRX_AUTH_KEY 가 없다"),  # 키를 안 넣은 환경
    ValueError("2026-10-27 105560·코스피 등락률 중 빈 칸이 있다"),
])
async def test_failure_returns_null_with_reason(krx, exc) -> None:
    kospi, _ = krx
    kospi.side_effect = exc

    compare, error = await mc.MarketCompare(object())(payload())

    assert compare is None
    assert error == f"{type(exc).__name__}: {exc}"


async def test_failure_is_tried_once_per_day(krx) -> None:
    """실패한 날은 다시 부르지 않는다. 그 날 보고서는 모두 같은 사유로 비교 없이 간다. 다른 날은 따로 부른다."""
    kospi, _ = krx

    async def fail_on_day(client, day):
        """2026-10-27 만 실패한다. 다른 날은 데이터가 없는 날(None)이다."""
        if day == DAY:
            raise KrxError("KRX kospi_dd_trd 20261027 요청 실패: ReadTimeout: ")

    kospi.side_effect = fail_on_day
    compare_for = mc.MarketCompare(object())

    same_day = [await compare_for(payload(code)) for code in ("005930", "105560", "000660")]
    other_day, other_error = await compare_for(payload(target_date="2026-10-28"))

    assert [c.args[1] for c in kospi.await_args_list] == [DAY, date(2026, 10, 28)]
    assert [c for c, _ in same_day] == [None, None, None]
    assert {e for _, e in same_day} == {"KrxError: KRX kospi_dd_trd 20261027 요청 실패: ReadTimeout: "}
    assert other_day["status"] == "no_data" and other_error is None


async def test_build_failure_affects_only_that_stock(krx) -> None:
    """응답은 받았는데 계산이 안 되는 종목(등락률 빈 칸)은 그 종목만 비교 없이 간다."""
    _, stocks = krx
    broken = STOCKS[1].model_copy(update={"change_rate": None})  # 삼성전자
    assert broken.code == "005930"
    stocks.return_value = [s if s.code != "005930" else broken for s in STOCKS]
    compare_for = mc.MarketCompare(object())

    samsung, samsung_error = await compare_for(payload("005930"))
    kb, kb_error = await compare_for(payload("105560"))

    assert samsung is None and samsung_error.startswith("ValueError: ")
    assert kb["status"] == "ok" and kb_error is None


async def test_other_errors_are_not_swallowed(krx) -> None:
    """코드 버그(TypeError 등)는 숨기지 않는다. KRX·계산 실패만 비교 없이 넘어간다."""
    kospi, _ = krx
    kospi.side_effect = TypeError("bug")
    with pytest.raises(TypeError):
        await mc.MarketCompare(object())(payload())
