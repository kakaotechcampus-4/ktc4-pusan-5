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


def report_input(cutoff: str = f"{TARGET_DATE}T15:30:00+09:00", *, market: dict | None = None) -> dict:
    """apply 가 보는 보고서 입력. change_pct −4.2 는 KRX(KB금융 0.27%)와 일부러 다르게 둔다."""
    default = {"index": "코스피", "change_pct": 3.09, "peer_median_pct": -0.6, "peer_up": 5, "peer_down": 13,
               "peer_total": 19, "excess_pct": -3.6}
    return {**payload(), "cutoff": cutoff, "change_pct": -4.2, "market": default if market is None else market}


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

    compare, failure = await mc.MarketCompare(object())(payload())

    assert compare is None
    assert str(failure) == f"{type(exc).__name__}: {exc}"
    assert failure.kind == type(exc).__name__ and failure.unexpected is False  # 예상한 실패


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
    assert {str(e) for _, e in same_day} == {"KrxError: KRX kospi_dd_trd 20261027 요청 실패: ReadTimeout: "}
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

    assert samsung is None and str(samsung_error).startswith("ValueError: ")
    assert kb["status"] == "ok" and kb_error is None


@pytest.mark.parametrize("exc", [
    AttributeError("'NoneType' object has no attribute 'get'"),  # KRX 응답 행이 객체가 아니다
    TypeError("bug"),  # 코드 버그
])
async def test_unexpected_fetch_error_fails_that_day_and_is_marked(krx, exc, caplog) -> None:
    """예상 밖 예외도 실행을 멈추지 않는다. 그 날짜 보고서는 모두 비교 없이 가고, 예상 밖으로 표시하고 ERROR 로 남긴다.
    다른 날은 영향이 없다."""
    kospi, _ = krx

    async def fail_on_day(client, day):
        """2026-10-27 만 예외다. 다른 날은 데이터가 없는 날(None)이다."""
        if day == DAY:
            raise exc

    kospi.side_effect = fail_on_day
    compare_for = mc.MarketCompare(object())

    with caplog.at_level("ERROR", logger=mc.__name__):
        same_day = [await compare_for(payload(code)) for code in ("005930", "105560")]
    other_day, other_failure = await compare_for(payload(target_date="2026-10-28"))

    assert [c for c, _ in same_day] == [None, None]
    assert {(f.kind, f.unexpected) for _, f in same_day} == {(type(exc).__name__, True)}
    assert kospi.await_count == 2  # 실패한 날도 한 번만 부른다
    assert "예상 밖 예외" in caplog.text and type(exc).__name__ in caplog.text
    assert other_failure is None and other_day["status"] == "no_data"  # 다른 날은 따로 부른다


async def test_unexpected_build_error_fails_only_that_stock(krx) -> None:
    """보통주가 대상 하나뿐인 응답이면 비중이 100% 라 (1 − 비중) 으로 나누다 ZeroDivisionError 가 난다. 그 종목만 실패다."""
    _, stocks = krx
    kb = next(s for s in STOCKS if s.code == "105560")
    stocks.return_value = [kb]
    compare_for = mc.MarketCompare(object())

    compare, failure = await compare_for(payload("105560"))

    assert compare is None
    assert failure.kind == "ZeroDivisionError" and failure.unexpected is True


async def test_unexpected_override_error_drops_market_compare(krx, monkeypatch) -> None:
    """입력 덮어쓰기에서 예외가 나면 시장 맥락 전체를 실패로 돌린다. 칸만 보내면 두 등락률이 섞인다."""
    def broken(*args, **kwargs):
        raise KeyError("peer_median_pct")

    monkeypatch.setattr(mc, "universe_peers", broken)
    original = report_input()

    sent, fields = await mc.MarketCompare(object()).apply(original)

    assert sent == {**original, "market_compare": None}
    assert fields["market_compare"] is None and fields["change_pct_override"] is None
    assert fields["market_compare_error_type"] == "KeyError" and fields["market_compare_unexpected"] is True


# --- 기준 시각과 입력 등락률 ---------------------------------------------------------------------


@pytest.mark.parametrize(("cutoff", "after"), [
    (f"{TARGET_DATE}T15:29:00+09:00", False),  # 경계: 장 마감 1분 전
    (f"{TARGET_DATE}T15:29:59+09:00", False),
    (f"{TARGET_DATE}T15:30:00+09:00", True),  # 경계: 장 마감 시각부터 이후다
    (f"{TARGET_DATE}T11:00:00+09:00", False),
    (f"{TARGET_DATE}T06:30:00+00:00", True),  # UTC 06:30 = KST 15:30. 시간대를 맞춰 비교한다
    ("2026-10-28T08:00:00+09:00", True),  # 다음 날 아침 기준 시각은 그날 장 마감 이후다
])
def test_after_close_boundary(cutoff: str, after: bool) -> None:
    assert mc.MARKET_CLOSE.isoformat() == "15:30:00"
    assert mc.after_close({**payload(), "cutoff": cutoff}) is after


async def test_before_close_skips_krx_and_keeps_input(krx) -> None:
    kospi, stocks = krx
    original = report_input(f"{TARGET_DATE}T15:29:00+09:00")

    sent, fields = await mc.MarketCompare(object()).apply(original)

    assert (kospi.await_count, stocks.await_count) == (0, 0)
    assert sent == {**original, "market_compare": None}
    assert fields == {"market_compare": None, "market_compare_error": None, "market_compare_error_type": None,
                      "market_compare_unexpected": False, "market_compare_skipped": mc.BEFORE_CLOSE,
                      "change_pct_override": None}


async def test_after_close_ok_overrides_change_pct_and_excess(krx) -> None:
    original = report_input()

    sent, fields = await mc.MarketCompare(object()).apply(original)

    assert fields["market_compare"]["status"] == "ok" and fields["market_compare_skipped"] is None
    assert sent["market_compare"] == fields["market_compare"]
    assert sent["change_pct"] == 0.27
    # 대형주 비교 수치는 KRX 응답의 유니버스 8종목(자기 제외)으로 다시 낸다. 지수 칸은 KRX 코스피 종가(3.09, 15:30)
    krx_peers = {"peer_median_pct": 3.84, "peer_up": 8, "peer_down": 0, "peer_total": 8}
    assert sent["market"] == {**original["market"], **krx_peers, "excess_pct": -3.57,  # 0.27 − 3.84
                              "change_pct": 3.09, "as_of": "15:30"}
    override = fields["change_pct_override"]
    assert {k: override[k] for k in ("input", "krx", "source", "excess_pct")} == {
        "input": -4.2, "krx": 0.27, "source": "KRX /sto/stk_bydd_trd 2026-10-27 FLUC_RT",
        "excess_pct": {"input": -3.6, "recomputed": -3.57}}
    assert override["peers"]["input"] == {"peer_median_pct": -0.6, "peer_up": 5, "peer_down": 13, "peer_total": 19}
    assert override["peers"]["krx"] == krx_peers
    # 받은 입력은 바꾸지 않는다
    assert original["change_pct"] == -4.2 and original["market"]["excess_pct"] == -3.6
    assert original["market"]["peer_median_pct"] == -0.6


@pytest.mark.parametrize("market", [
    None,  # market 칸이 null
    {"index": "코스피", "change_pct": 3.09, "peer_median_pct": None, "excess_pct": None},  # 중간값이 없다
])
async def test_override_without_peer_median_leaves_peers(krx, market) -> None:
    """입력에 중간값이 없으면 대형주 비교 수치를 건드리지 않는다. 없던 대형주 비교를 KRX 로 새로 켜지 않는다.
    지수 등락률은 있으면 KRX 로 바꾼다. market 이 null 이면 그대로 null 이다."""
    original = {**report_input(), "market": market}

    sent, fields = await mc.MarketCompare(object()).apply(original)

    assert sent["change_pct"] == 0.27
    assert sent["market"] == (None if market is None else {**market, "change_pct": 3.09, "as_of": "15:30"})
    assert fields["change_pct_override"]["peers"] is None
    assert fields["change_pct_override"]["excess_pct"] is None


def universe_stock(code: str, rate: float | None, *, volume: int = 1000):
    return STOCKS[0].model_copy(update={"code": code, "name": code, "change_rate": rate, "volume": volume})


def test_universe_peers_leaves_out_self_missing_no_trades_and_blank_rate() -> None:
    """유니버스 7종목: 자기 자신 1, 응답에 없음 1, 거래정지 1, 등락률 빈 칸 1 을 빼면 3종목(−1.0, 0.0, 2.0)이 남는다.
    보합 0.0 은 전체 수에만 든다."""
    stocks = [
        universe_stock("000010", 5.0),  # 대상 자신
        universe_stock("000020", -1.0),
        universe_stock("000030", 0.0),
        universe_stock("000040", 2.0),
        universe_stock("000050", 0.0, volume=0),  # 거래정지: 0.00 은 보합이 아니다
        universe_stock("000060", None),
    ]
    universe = ("000010", "000020", "000030", "000040", "000050", "000060", "000070")

    peers, excluded = mc.universe_peers(stocks, "000010", universe)

    assert peers == {"peer_median_pct": 0.0, "peer_up": 1, "peer_down": 1, "peer_total": 3}
    assert excluded == [{"code": "000050", "reason": "no_trades"}, {"code": "000060", "reason": "no_rate"},
                        {"code": "000070", "reason": "missing"}]


def test_universe_peers_median_of_even_count_is_rounded() -> None:
    stocks = [universe_stock(c, r) for c, r in (("000020", 0.35), ("000030", 0.80))]
    peers, _ = mc.universe_peers(stocks, "000010", ("000020", "000030"))
    assert peers["peer_median_pct"] == round((0.35 + 0.80) / 2, 2)


def test_universe_peers_none_when_nothing_usable() -> None:
    peers, excluded = mc.universe_peers([], "000010", ("000020",))
    assert peers is None and excluded == [{"code": "000020", "reason": "missing"}]


def test_override_falls_back_to_input_median_when_universe_is_empty() -> None:
    """쓸 유니버스 종목이 하나도 없으면 입력 중간값·종목 수를 두고 excess_pct 만 새 change_pct 로 다시 낸다."""
    original = report_input()
    compare = mc.to_input(build_market_context("105560", DAY, KOSPI, STOCKS))

    sent, record = mc.override_change_pct(original, compare, STOCKS, universe=("999990",))

    assert sent["market"] == {**original["market"], "excess_pct": 0.87,  # 0.27 − (−0.6)
                              "change_pct": 3.09, "as_of": "15:30"}
    assert record["peers"] == {"input": {"peer_median_pct": -0.6, "peer_up": 5, "peer_down": 13, "peer_total": 19},
                               "krx": None, "excluded": [{"code": "999990", "reason": "missing"}]}
    assert record["excess_pct"] == {"input": -3.6, "recomputed": 0.87}


@pytest.mark.parametrize(("setup", "status"), [
    ("no_data", "no_data"),  # 장 마감 이후인데 KRX 데이터가 없다
    ("failed", None),  # KRX 호출 실패
    ("no_trades", "no_trades"),  # 거래정지. 0.00 은 보합이 아니라 덮어쓰지 않는다
])
async def test_after_close_without_ok_keeps_input(krx, setup, status) -> None:
    kospi, stocks = krx
    if setup == "no_data":
        kospi.return_value = None
    elif setup == "failed":
        kospi.side_effect = KrxError("KRX kospi_dd_trd 20261027 요청 실패: ReadTimeout: ")
    else:
        halted = STOCKS[6].model_copy(update={"volume": 0, "change_rate": 0.0})  # KB금융을 거래정지로
        assert halted.code == "105560"
        stocks.return_value = [halted if s.code == "105560" else s for s in STOCKS]
    original = report_input()

    sent, fields = await mc.MarketCompare(object()).apply(original)

    assert (sent["market_compare"] or {}).get("status") == status
    assert sent["change_pct"] == -4.2 and sent["market"] == original["market"]
    assert fields["change_pct_override"] is None
    assert (fields["market_compare_error"] is not None) is (setup == "failed")


# --- 지수 등락률도 KRX 로 ------------------------------------------------------------------------


async def test_after_close_ok_overrides_index_change_pct_and_as_of(krx) -> None:
    """입력 지수 등락률(−0.50, 14:00)과 KRX 코스피 등락률(3.09, 종가)이 한 입력에 같이 있으면 모델이 어느 쪽을 쓸지 모른다.
    덮어쓸 때 지수 칸도 KRX 로 바꾸고 원래 값을 래퍼에 남긴다. 정형 보고서 move 문장도 같은 값을 쓴다."""
    from app.services.stock_analysis.generate import canned_report

    market = {"index": "코스피", "change_pct": -0.5, "as_of": "14:00", "peer_median_pct": -0.6, "peer_up": 5,
              "peer_down": 13, "peer_total": 19, "excess_pct": -3.6}
    original = report_input(market=market)

    sent, fields = await mc.MarketCompare(object()).apply(original)

    assert sent["market_compare"]["kospi"]["kospi_change_rate_pct"] == 3.09
    assert (sent["market"]["change_pct"], sent["market"]["as_of"]) == (3.09, "15:30")
    assert fields["change_pct_override"]["index"] == {
        "input": {"change_pct": -0.5, "as_of": "14:00"}, "krx": {"change_pct": 3.09, "as_of": "15:30"},
        "source": "KRX /idx/kospi_dd_trd 2026-10-27 코스피 FLUC_RT"}
    assert "코스피는 3.09% 올랐" in canned_report({**sent, "stock": "KB금융"})["summary"]["move"]
    assert original["market"]["change_pct"] == -0.5  # 받은 입력은 바꾸지 않는다


async def test_override_leaves_missing_index_change_pct(krx) -> None:
    """입력에 지수 등락률이 없으면 새로 켜지 않는다(정형 보고서의 지수 문장이 새로 생기면 안 된다)."""
    market = {"index": "코스피", "change_pct": None, "peer_median_pct": -0.6, "peer_up": 5, "peer_down": 13,
              "peer_total": 19, "excess_pct": -3.6}

    sent, fields = await mc.MarketCompare(object()).apply(report_input(market=market))

    assert sent["market"]["change_pct"] is None and "as_of" not in sent["market"]
    assert fields["change_pct_override"]["index"] is None


# --- 장 마감이 늦춰지는 날 -----------------------------------------------------------------------


@pytest.mark.parametrize(("cutoff", "after"), [
    ("2026-11-19T15:30:00+09:00", False),  # 수능일. 15:30 은 아직 장중이다
    ("2026-11-19T16:29:00+09:00", False),
    ("2026-11-19T16:30:00+09:00", True),
    ("2026-11-20T15:30:00+09:00", True),  # 다음 날은 평소대로
])
def test_after_close_uses_late_close_day(cutoff: str, after: bool) -> None:
    assert mc.after_close({"target_date": cutoff[:10], "cutoff": cutoff}) is after


# --- 공유 Task 취소와 실패 로그 ------------------------------------------------------------------


async def test_cancelling_one_report_does_not_cancel_shared_day(krx) -> None:
    """같은 날 보고서 하나가 취소돼도 기준일 Task 는 계속 돌고, 다른 보고서는 결과를 받는다."""
    kospi, _ = krx
    release = asyncio.Event()

    async def slow_kospi(client, day):
        await release.wait()
        return KOSPI

    kospi.side_effect = slow_kospi
    compare_for = mc.MarketCompare(object())
    cancelled = asyncio.create_task(compare_for(payload("005930")))
    other = asyncio.create_task(compare_for(payload("105560")))
    await asyncio.sleep(0)
    cancelled.cancel()
    await asyncio.sleep(0)
    release.set()

    compare, failure = await other
    assert failure is None and compare["status"] == "ok"
    assert cancelled.cancelled()
    assert not compare_for._days[DAY].cancelled()


@pytest.mark.parametrize(("exc", "level"), [
    (KrxError("KRX kospi_dd_trd 20261027 요청 실패: ReadTimeout: "), "WARNING"),
    (TypeError("bug"), "ERROR"),
])
async def test_day_failure_is_logged_once_per_day(krx, caplog, exc, level) -> None:
    """같은 날 보고서 셋이 같은 KRX 실패를 받아도 로그는 그 날짜에 한 번이다. 보고서마다 실패 사유는 그대로 받는다."""
    kospi, _ = krx
    kospi.side_effect = exc
    compare_for = mc.MarketCompare(object())

    with caplog.at_level("WARNING", logger=mc.__name__):
        results = [await compare_for(payload(code)) for code in ("005930", "105560", "000660")]

    assert {str(f) for _, f in results} == {f"{type(exc).__name__}: {exc}"}
    assert [r.levelname for r in caplog.records] == [level]
