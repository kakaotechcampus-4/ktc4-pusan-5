from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.exc import SQLAlchemyError

from app.collectors import stocks
from app.core.config import settings
from app.repositories import market_calendar as calendar_repo
from app.services.kis import KisClient
from app.services.market_calendar import KST, TradingCalendar
from app.services.market_data import MarketDataError

PATH = "/uapi/domestic-stock/v1/quotations/chk-holiday"


def _row(bass_dt, opnd_yn):
    return {
        "bass_dt": bass_dt,
        "wday_dvsn_cd": "02",
        "bzdy_yn": opnd_yn,
        "tr_day_yn": "Y",
        "opnd_yn": opnd_yn,
        "sttl_day_yn": opnd_yn,
    }


def _body(output):
    return {"rt_cd": "0", "msg_cd": "KIOK0500", "msg1": "조회가 계속됩니다..", "output": output}


@pytest.fixture
def kis_keys(monkeypatch):
    monkeypatch.setattr(settings, "kis_app_key", "test-only")
    monkeypatch.setattr(settings, "kis_app_secret", "test-only")
    monkeypatch.setattr(settings, "kis_request_interval_seconds", 0)
    respx.post(settings.kis_api_base_url + "/oauth2/tokenP").mock(
        return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
    )


@respx.mock
async def test_market_calendar_reads_opnd_yn(kis_keys):
    route = respx.get(settings.kis_api_base_url + PATH).mock(
        return_value=httpx.Response(
            200,
            json=_body([_row("20261031", "N"), _row("20261101", "N"), _row("20261102", "Y")]),
        )
    )
    async with httpx.AsyncClient() as client:
        days = await KisClient(client).fetch_market_calendar(date(2026, 10, 31))
    assert days == [
        (date(2026, 10, 31), False),
        (date(2026, 11, 1), False),
        (date(2026, 11, 2), True),
    ]
    request = route.calls.last.request
    assert request.headers["tr_id"] == "CTCA0903R"
    assert request.url.params["BASS_DT"] == "20261031"
    assert request.url.params["CTX_AREA_NK"] == ""


@pytest.mark.parametrize(
    "output",
    [
        None,
        {},
        [],
        ["20261031"],
        [_row("20261031", "y")],  # opnd_yn 이 Y/N 이 아님
        [{"bass_dt": "20261031"}],  # opnd_yn 없음
        [_row("2026-10-31", "Y")],  # 8자리가 아님
        [_row("20261341", "Y")],  # 날짜가 아님
        [_row(20261031, "Y")],  # 문자열이 아님
    ],
)
@respx.mock
async def test_market_calendar_rejects_invalid_output(kis_keys, output):
    respx.get(settings.kis_api_base_url + PATH).mock(
        return_value=httpx.Response(200, json=_body(output))
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(MarketDataError, match="INVALID_RESPONSE"):
            await KisClient(client).fetch_market_calendar(date(2026, 10, 31))


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        pass


class FakeKis:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    async def fetch_market_calendar(self, day):
        self.calls += 1
        if self.error:
            raise self.error
        return [(day, False)]


class Clock:
    def __init__(self, now):
        self.now = now


@pytest.fixture
def worker_env(monkeypatch):
    """DB 대신 메모리 저장소와 고정 시계를 쓰는 StockWorker 환경."""
    clock = Clock(datetime(2026, 12, 25, 1, 0, tzinfo=UTC))
    store = {"rows": {}, "fetched": [], "lookups": 0}

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now

    async def fetched_on(session, day):
        store["lookups"] += 1
        return any(at.astimezone(KST).date() == day for at in store["fetched"])

    async def upsert_days(session, days, fetched_at):
        store["rows"].update(days)
        store["fetched"].append(fetched_at)

    async def load_calendar(session, now):
        return TradingCalendar(dict(store["rows"]))

    monkeypatch.setattr(stocks, "datetime", FakeDatetime)
    monkeypatch.setattr(stocks, "SessionLocal", FakeSession)
    monkeypatch.setattr(calendar_repo, "fetched_on", fetched_on)
    monkeypatch.setattr(calendar_repo, "upsert_days", upsert_days)
    monkeypatch.setattr(calendar_repo, "load_calendar", load_calendar)
    return clock, store


async def test_refresh_skips_kis_when_fetched_today(worker_env):
    clock, store = worker_env
    store["fetched"].append(clock.now - timedelta(minutes=30))  # 재시작 전에 받은 기록
    kis = FakeKis()
    worker = stocks.StockWorker(None, kis)
    await worker.refresh_calendar()
    assert kis.calls == 0
    assert store["lookups"] == 1


async def test_refresh_fetches_once_per_day_without_repeating_db_lookup(worker_env):
    clock, store = worker_env
    kis = FakeKis()
    worker = stocks.StockWorker(None, kis)
    await worker.refresh_calendar()
    assert kis.calls == 1
    assert store["rows"] == {date(2026, 12, 25): False}

    # 같은 날 다음 tick 에서는 KIS 도 DB 도 보지 않는다.
    clock.now += timedelta(hours=5)
    await worker.refresh_calendar()
    assert kis.calls == 1
    assert store["lookups"] == 1

    # 다음 날(KST)에는 다시 받는다.
    clock.now += timedelta(days=1)
    await worker.refresh_calendar()
    assert kis.calls == 2


async def test_failed_refresh_waits_one_hour(worker_env, caplog):
    clock, store = worker_env
    kis = FakeKis(MarketDataError("UPSTREAM_ERROR"))
    worker = stocks.StockWorker(None, kis)
    await worker.refresh_calendar()
    assert kis.calls == 1
    assert "judging by weekdays" in caplog.text

    clock.now += timedelta(minutes=59)
    await worker.refresh_calendar()
    assert kis.calls == 1

    clock.now += timedelta(minutes=1)
    kis.error = None
    await worker.refresh_calendar()
    assert kis.calls == 2
    assert date(2026, 12, 25) in store["rows"]


async def test_db_error_after_kis_success_still_waits_one_hour(worker_env, monkeypatch):
    clock, _store = worker_env

    async def failing_upsert(session, days, fetched_at):
        raise SQLAlchemyError("x")

    monkeypatch.setattr(calendar_repo, "upsert_days", failing_upsert)
    kis = FakeKis()
    worker = stocks.StockWorker(None, kis)
    # DB 예외는 삼키지 않고 수집기 루프로 올라간다.
    with pytest.raises(SQLAlchemyError):
        await worker.refresh_calendar()
    assert kis.calls == 1

    # 루프가 곧바로 다음 tick 을 돌려도 1시간 안에는 KIS 를 다시 부르지 않는다.
    clock.now += timedelta(seconds=5)
    await worker.refresh_calendar()
    clock.now += timedelta(minutes=58)
    await worker.refresh_calendar()
    assert kis.calls == 1

    clock.now += timedelta(minutes=2)
    with pytest.raises(SQLAlchemyError):
        await worker.refresh_calendar()
    assert kis.calls == 2
