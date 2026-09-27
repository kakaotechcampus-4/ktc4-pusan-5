from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from app.core.config import settings
from app.services import fred, krx
from app.services.kis import KisClient
from app.services.market_data import INDICATORS, MarketDataError, number


@pytest.fixture(autouse=True)
def configured_keys(monkeypatch):
    for key in ("fred_api_key", "krx_auth_key", "kis_app_key", "kis_app_secret"):
        monkeypatch.setattr(settings, key, "test-only")


@respx.mock
async def test_fred_skips_missing_days_and_computes_change():
    respx.get(settings.fred_api_base_url + "/series/observations").mock(
        return_value=httpx.Response(
            200,
            json={
                "observations": [
                    {"date": "2026-09-20", "value": "."},
                    {"date": "2026-09-18", "value": "110"},
                    {"date": "2026-09-17", "value": "."},
                    {"date": "2026-09-16", "value": "100"},
                ]
            },
        )
    )
    async with httpx.AsyncClient() as client:
        quote = await fred.fetch_quote(client, "SP500")
    assert quote.value == 110
    assert quote.change == 10
    assert quote.observation_date == date(2026, 9, 18)


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "", ".", None, "1e30"])
def test_invalid_numbers_are_not_stored(raw):
    with pytest.raises(MarketDataError):
        number(raw)


@respx.mock
async def test_krx_falls_back_after_empty_day_and_selects_exact_index():
    route = respx.get(settings.krx_api_base_url + "/idx/kospi_dd_trd")
    route.side_effect = [
        httpx.Response(200, json={"OutBlock_1": []}),
        httpx.Response(
            200,
            json={
                "OutBlock_1": [
                    {"IDX_NM": "코스피 200"},
                    {
                        "IDX_NM": "코스피",
                        "CLSPRC_IDX": "6,894.23",
                        "FLUC_RT": "-1.25",
                        "BAS_DD": "20260918",
                    },
                ]
            },
        ),
    ]
    async with httpx.AsyncClient() as client:
        quote = await krx.fetch_quote(client, INDICATORS[0])
    assert quote.value == Decimal("6894.23")
    assert quote.change == Decimal("-1.25")
    assert route.call_count == 2
    assert route.calls[0].request.url.params["basDd"] != route.calls[1].request.url.params["basDd"]


@respx.mock
async def test_krx_auth_failure_is_not_retried_as_a_holiday():
    route = respx.get(settings.krx_api_base_url + "/idx/kospi_dd_trd").mock(
        return_value=httpx.Response(401)
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await krx.fetch_quote(client, INDICATORS[0])
    assert route.call_count == 1


@respx.mock
async def test_kis_reuses_token_and_uses_dated_quote():
    auth = respx.post(settings.kis_api_base_url + "/oauth2/tokenP").mock(
        return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
    )
    respx.get(
        settings.kis_api_base_url + "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "output1": {"ovrs_nmix_prpr": "9999"},
                "output2": [
                    {"stck_bsop_date": "20260917", "ovrs_nmix_prpr": "1000"},
                    {"stck_bsop_date": "20260918", "ovrs_nmix_prpr": "1100"},
                ],
            },
        )
    )
    async with httpx.AsyncClient() as client:
        kis = KisClient(client)
        first = await kis.fetch_quote()
        second = await kis.fetch_quote()
    assert first == second
    assert first.value == 1100
    assert first.change == 10
    assert auth.call_count == 1


@pytest.mark.parametrize("payload", [[], None, "bad", 42, {"rt_cd": "0", "output2": [None]}])
@respx.mock
async def test_malformed_kis_response_is_contained_and_next_fetch_succeeds(payload):
    import json

    from app.collectors.market import fetch_result

    respx.post(settings.kis_api_base_url + "/oauth2/tokenP").respond(
        200, json={"access_token": "test-token", "expires_in": 86400}
    )
    route = respx.get(
        settings.kis_api_base_url + "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
    )
    route.side_effect = [
        httpx.Response(200, content=json.dumps(payload)),
        httpx.Response(
            200,
            json={
                "rt_cd": "0",
                "output2": [
                    {"stck_bsop_date": "20260918", "ovrs_nmix_prpr": "1100"},
                    {"stck_bsop_date": "20260917", "ovrs_nmix_prpr": "1000"},
                ],
            },
        ),
    ]
    async with httpx.AsyncClient() as client:
        kis = KisClient(client)
        _, value, error = await fetch_result("usdkrw", kis.fetch_quote)
        assert value is None
        assert error == "INVALID_RESPONSE"
        _, value, error = await fetch_result("usdkrw", kis.fetch_quote)
        assert value.value == 1100
        assert error is None
