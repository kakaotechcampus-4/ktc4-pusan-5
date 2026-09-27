import asyncio
import time
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from types import SimpleNamespace

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.ranking import RankingSnapshot
from app.repositories.ranking import save_ranking
from app.routers import market
from app.services.kis import KisClient
from app.services.market_data import MarketDataError
from app.services.ranking import parse_ranking, ranking_boards


def raw(rank=1, code="000660", value="8000000000000"):
    return {
        "data_rank": str(rank),
        "mksc_shrn_iscd": code,
        "hts_kor_isnm": "테스트 종목",
        "stck_prpr": "1849000",
        "prdy_ctrt": "-1.25",
        "acml_vol": "4000000",
        "acml_tr_pbmn": value,
    }


def test_rank_and_trading_value_are_preserved_without_resorting_a_partial_pool():
    items = parse_ranking([raw(2, "005930", "9999999999999"), raw()])
    assert [item.rank for item in items] == [1, 2]
    assert items[0].trading_value == 8000000000000
    assert items[0].change == -1.25


@pytest.mark.parametrize(
    "rows",
    [[raw(), raw()], [raw(value="NaN")], [raw(value="12.5")], [raw(value="9007199254740992")]],
)
def test_bad_or_duplicate_ranking_does_not_replace_snapshot(rows):
    with pytest.raises((MarketDataError, ValueError)):
        parse_ranking(rows)


@pytest.fixture
def kis_keys(monkeypatch):
    monkeypatch.setattr(settings, "kis_app_key", "test-only")
    monkeypatch.setattr(settings, "kis_app_secret", "test-only")


@respx.mock
async def test_fx_and_four_ranking_tabs_share_one_token_and_paced_requests(kis_keys):
    auth = respx.post(settings.kis_api_base_url + "/oauth2/tokenP").mock(
        return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
    )
    starts = []
    ranks = []

    def quote_response(request):
        starts.append(time.monotonic())
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "output2": [
                    {"stck_bsop_date": "20260918", "ovrs_nmix_prpr": "1100"},
                    {"stck_bsop_date": "20260917", "ovrs_nmix_prpr": "1000"},
                ],
            },
        )

    def ranking_response(request):
        starts.append(time.monotonic())
        ranks.append(request.url.params["FID_BLNG_CLS_CODE"])
        assert request.url.params["FID_DIV_CLS_CODE"] == "1"
        assert request.url.params["FID_TRGT_EXLS_CLS_CODE"] == "0010011101"
        return httpx.Response(200, json={"rt_cd": "0", "output": [raw()]})

    respx.get(
        settings.kis_api_base_url + "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
    ).mock(side_effect=quote_response)
    respx.get(settings.kis_api_base_url + "/uapi/domestic-stock/v1/quotations/volume-rank").mock(
        side_effect=ranking_response
    )

    def fluctuation_response(request):
        starts.append(time.monotonic())
        rate = 10 if request.url.params["FID_RANK_SORT_CLS_CODE"] == "0" else -10
        return httpx.Response(200, json={"rt_cd": "0", "output": [fluctuation_raw(1, rate)]})

    respx.get(settings.kis_api_base_url + "/uapi/domestic-stock/v1/ranking/fluctuation").mock(
        side_effect=fluctuation_response
    )
    async with httpx.AsyncClient() as client:
        kis = KisClient(client)
        await asyncio.gather(
            kis.fetch_quote(),
            kis.fetch_ranking("tradingValue"),
            kis.fetch_ranking("volume"),
            kis.fetch_ranking("gainers"),
            kis.fetch_ranking("losers"),
        )
    assert len(starts) == 5
    assert auth.call_count == 1
    assert sorted(ranks) == ["0", "3"]
    assert all(b - a >= 0.5 for a, b in pairwise(starts))


@respx.mock
async def test_auth_failure_does_not_trigger_three_token_requests(kis_keys):
    auth = respx.post(settings.kis_api_base_url + "/oauth2/tokenP").mock(
        return_value=httpx.Response(403)
    )
    async with httpx.AsyncClient() as client:
        kis = KisClient(client)
        results = await asyncio.gather(
            kis.fetch_quote(),
            kis.fetch_ranking("tradingValue"),
            kis.fetch_ranking("volume"),
            return_exceptions=True,
        )
    assert auth.call_count == 1
    assert all(isinstance(result, Exception) for result in results)


async def test_failed_refresh_retains_batch_and_empty_success_clears_it():
    async with SessionLocal() as session:
        try:
            now = datetime.now(UTC)
            await save_ranking(
                session, "test-ranking", parse_ranking([raw(), raw(2, "005930")]), None, now
            )
            await save_ranking(
                session, "test-ranking", None, "UPSTREAM_TIMEOUT", now + timedelta(seconds=60)
            )
            row = await session.scalar(
                select(RankingSnapshot).where(RankingSnapshot.kind == "test-ranking")
            )
            assert len(row.items) == 2
            assert row.error_code == "UPSTREAM_TIMEOUT"
            await save_ranking(session, "test-ranking", [], None, now + timedelta(seconds=120))
            await session.refresh(row)
            assert row.items == []
            assert row.error_code is None
        finally:
            await session.rollback()


def test_board_statuses_and_limit():
    now = datetime.now(UTC)
    rows = parse_ranking([raw(n, f"{n:06}") for n in range(1, 31)])
    result = ranking_boards(
        {
            "tradingValue": SimpleNamespace(
                items=[item.model_dump() for item in rows],
                collected_at=now - timedelta(seconds=181),
                error_code=None,
            ),
            "volume": SimpleNamespace(items=[], collected_at=now, error_code=None),
        }
    )
    assert [board.status for board in result] == [
        "stale",
        "empty",
        "pending",
        "pending",
    ]
    assert len(result[0].items) == 10


@respx.mock
async def test_overview_and_dedicated_endpoint_read_same_rankings_without_upstream(monkeypatch):
    async def rankings(session):
        return {
            "volume": SimpleNamespace(
                items=[item.model_dump() for item in parse_ranking([raw()])],
                collected_at=datetime.now(UTC),
                error_code=None,
            )
        }

    async def snapshots(session):
        return {}

    monkeypatch.setattr(market, "list_rankings", rankings)
    monkeypatch.setattr(market, "list_snapshots", snapshots)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/api/market/overview")
        second = await client.get("/api/market/rankings")
    assert first.status_code == second.status_code == 200
    item = second.json()["rankings"][1]["items"][0]
    assert item["tradingValue"] == 8000000000000
    assert first.json()["rankings"][1]["items"] == second.json()["rankings"][1]["items"]
    assert len(respx.calls) == 0


def fluctuation_raw(rank, change):
    row = raw(rank, f"{rank:06}")
    row["stck_shrn_iscd"] = row.pop("mksc_shrn_iscd")
    del row["acml_tr_pbmn"]
    row["prdy_ctrt"] = str(change)
    return row


@pytest.mark.parametrize(
    "kind,rates", [("gainers", [29.97, 29.97, 12, 0, -1]), ("losers", [-29.96, -29.96, -12, 0, 1])]
)
def test_fluctuation_preserves_ties_and_excludes_other_direction(kind, rates):
    rows = [fluctuation_raw(i, rate) for i, rate in enumerate(rates, 1)]
    items = parse_ranking(list(reversed(rows)), kind)
    assert [item.rank for item in items] == [1, 2, 3]
    assert all(item.trading_value is None for item in items)
    assert parse_ranking([], kind) == []


@pytest.mark.parametrize("kind,rates", [("gainers", [29.90, 29.97]), ("losers", [-20, -29])])
def test_fluctuation_rejects_wrong_upstream_order(kind, rates):
    with pytest.raises(MarketDataError, match="INVALID_RANK_ORDER"):
        parse_ranking([fluctuation_raw(i, rate) for i, rate in enumerate(rates, 1)], kind)


@respx.mock
async def test_fluctuation_uses_verified_previous_close_sort(kis_keys):
    respx.post(settings.kis_api_base_url + "/oauth2/tokenP").respond(
        200, json={"access_token": "test-token", "expires_in": 86400}
    )
    sorts = []

    def response(request):
        p = request.url.params
        assert request.headers["tr_id"] == "FHPST01700000"
        assert p["FID_PRC_CLS_CODE"] == "1"
        assert p["FID_DIV_CLS_CODE"] == "1"
        assert p["FID_TRGT_EXLS_CLS_CODE"] == "0010011101"
        sorts.append(p["FID_RANK_SORT_CLS_CODE"])
        rates = [29.97, 29.90] if sorts[-1] == "0" else [-29.96, -20]
        return httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "output": [fluctuation_raw(i, rate) for i, rate in enumerate(rates, 1)],
            },
        )

    respx.get(settings.kis_api_base_url + "/uapi/domestic-stock/v1/ranking/fluctuation").mock(
        side_effect=response
    )
    async with httpx.AsyncClient() as client:
        kis = KisClient(client)
        results = await asyncio.gather(kis.fetch_ranking("gainers"), kis.fetch_ranking("losers"))
    assert sorted(sorts) == ["0", "1"]
    assert all(len(items) == 2 for items in results)
