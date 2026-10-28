import time
from itertools import pairwise

import httpx
import pytest
import respx

from app.core.config import settings
from app.services.kis import RATE_LIMIT_RETRIES, KisClient

PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
INTERVAL = 0.05
RATE_LIMITED = httpx.Response(
    500, json={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."}
)
OK = httpx.Response(200, json={"rt_cd": "0", "output": {}})


@pytest.fixture
def kis_keys(monkeypatch):
    monkeypatch.setattr(settings, "kis_app_key", "test-only")
    monkeypatch.setattr(settings, "kis_app_secret", "test-only")
    monkeypatch.setattr(settings, "kis_request_interval_seconds", INTERVAL)
    respx.post(settings.kis_api_base_url + "/oauth2/tokenP").mock(
        return_value=httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
    )


@respx.mock
async def test_rate_limited_request_is_retried_after_one_interval(kis_keys):
    starts = []
    responses = iter([RATE_LIMITED, OK])

    def respond(request):
        starts.append(time.monotonic())
        return next(responses)

    route = respx.get(settings.kis_api_base_url + PATH).mock(side_effect=respond)
    async with httpx.AsyncClient() as client:
        body = await KisClient(client).get(PATH, "FHKST01010100", {})
    assert body["rt_cd"] == "0"
    assert route.call_count == 2
    assert starts[1] - starts[0] >= INTERVAL * 0.9


@respx.mock
async def test_repeated_rate_limit_fails_only_that_request_without_global_pause(kis_keys):
    route = respx.get(settings.kis_api_base_url + PATH).mock(
        side_effect=[RATE_LIMITED] * (RATE_LIMIT_RETRIES + 1) + [OK]
    )
    async with httpx.AsyncClient() as client:
        kis = KisClient(client)
        with pytest.raises(httpx.HTTPStatusError):
            await kis.get(PATH, "FHKST01010100", {})
        assert route.call_count == RATE_LIMIT_RETRIES + 1
        # 예전에는 여기서 60초 동안 모든 요청이 멈췄다. 이제 다음 요청은 한 간격 뒤에 나간다.
        started = time.monotonic()
        body = await kis.get(PATH, "FHKST01010100", {})
    assert body["rt_cd"] == "0"
    assert time.monotonic() - started < 1


@respx.mock
async def test_requests_keep_configured_interval(kis_keys):
    starts = []

    def respond(request):
        starts.append(time.monotonic())
        return OK

    respx.get(settings.kis_api_base_url + PATH).mock(side_effect=respond)
    async with httpx.AsyncClient() as client:
        kis = KisClient(client)
        for _ in range(3):
            await kis.get(PATH, "FHKST01010100", {})
    assert all(b - a >= INTERVAL * 0.9 for a, b in pairwise(starts))
