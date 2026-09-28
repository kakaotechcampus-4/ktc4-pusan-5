"""토큰 추정치보다 프로바이더 사용료를 우선하고 응답 중단 사유를 보존한다."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.llm import client


@pytest.fixture(autouse=True)
def openrouter_unless_told(monkeypatch):
    """settings 는 개발자 각자의 ai/.env 를 읽는다. 누군가 LLM_PROVIDER=elice 를
    넣어 두면 OpenRouter 를 전제한 테스트가 그 사람 컴퓨터에서만 깨진다.
    Elice 를 보는 테스트는 안에서 다시 바꾼다.
    """
    monkeypatch.setattr(client.settings, "llm_provider", "openrouter")


def test_provider_cost_takes_precedence():
    assert client.cost({"cost": 0.123, "prompt_tokens": 1000}) == 0.123
    assert client.cost({"cost": 0.0, "prompt_tokens": 1000}) == 0.0
    assert client.cost({"prompt_tokens": 1000}) == pytest.approx(0.00006)
    assert client.cost_currency() == "USD"


def _elice(monkeypatch, *, input_krw=300.0, output_krw=2500.0):
    """단가를 테스트 안에서 고정한다. 개인 ai/.env 의 단가가 기대값을 흔들지 않게."""
    monkeypatch.setattr(client.settings, "llm_provider", "elice")
    monkeypatch.setattr(client.settings, "llm_base_url", "https://mlapi.run/abc/v1/")
    monkeypatch.setattr(client.settings, "llm_api_key", "test-only")
    monkeypatch.setattr(client.settings, "llm_input_krw_per_m", input_krw)
    monkeypatch.setattr(client.settings, "llm_output_krw_per_m", output_krw)


@pytest.mark.parametrize("effort, expected", [
    ("low", {"effort": "low"}), ("none", {"enabled": False}),
])
async def test_nonempty_truncated_response_keeps_finish_reason(monkeypatch, effort, expected):
    monkeypatch.setattr(client.settings, "openrouter_api_key", "test-only")
    monkeypatch.setattr(client.settings, "summary_reasoning_effort", effort)
    response = MagicMock()
    response.json.return_value = {
        "choices": [{"message": {"content": "완성되지 않은 문장"}, "finish_reason": "length"}],
        "usage": {"cost": 0.01, "completion_tokens": 8000},
    }
    http = AsyncMock()
    http.post.return_value = response
    manager = AsyncMock()
    manager.__aenter__.return_value = http
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: manager)
    text, usage = await client.complete("test", "test")
    assert text == "완성되지 않은 문장"
    assert usage["finish_reason"] == "length"
    assert usage["cost"] == 0.01
    assert http.post.await_args.kwargs["json"]["reasoning"] == expected


def _fake_http(monkeypatch, body: dict) -> AsyncMock:
    response = MagicMock()
    response.json.return_value = body
    http = AsyncMock()
    http.post.return_value = response
    manager = AsyncMock()
    manager.__aenter__.return_value = http
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: manager)
    return http


async def test_elice_uses_its_own_parameter_names(monkeypatch):
    """Elice 는 모르는 매개변수를 400 으로 거절한다. OpenRouter 전용 이름이 새면 안 된다."""
    _elice(monkeypatch)
    monkeypatch.setattr(client.settings, "summary_reasoning_effort", "minimal")
    http = _fake_http(monkeypatch, {
        "choices": [{"message": {"content": "안녕"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
    })
    text, usage = await client.complete("test", "test", max_tokens=100)

    assert text == "안녕"
    assert http.post.await_args.args[0] == "https://mlapi.run/abc/v1/chat/completions"
    sent = http.post.await_args.kwargs["json"]
    assert sent["max_completion_tokens"] == 100
    assert sent["reasoning_effort"] == "minimal"
    assert "max_tokens" not in sent and "reasoning" not in sent
    # 응답에 비용이 없으니 원화 단가로 계산한다. ₩300 + ₩2,500
    assert client.cost(usage) == pytest.approx(2800)
    assert usage["cost_currency"] == "KRW"


async def test_http_error_keeps_status_and_provider_message(monkeypatch):
    """예외 이름만 남기면 429 인지 400 인지 몰라 고칠 곳을 못 찾는다."""
    monkeypatch.setattr(client.settings, "openrouter_api_key", "test-only")
    request = client.httpx.Request("POST", client.OPENROUTER_URL)
    response = client.httpx.Response(429, request=request, text='{"error":"rate limited"}')
    http = _fake_http(monkeypatch, {})
    http.post.return_value = response
    with pytest.raises(client.LLMError, match=r"HTTP 429 .*rate limited"):
        await client.complete("test", "test")


def test_elice_without_address_stops_before_calling(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_provider", "elice")
    monkeypatch.setattr(client.settings, "llm_base_url", None)
    monkeypatch.setattr(client.settings, "llm_api_key", "test-only")
    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        client.endpoint()


def test_openrouter_is_still_the_default(monkeypatch):
    """이 설정이 없는 팀원의 .env 는 지금처럼 OpenRouter 로 가야 한다."""
    assert Settings.model_fields["llm_provider"].default == "openrouter"
    monkeypatch.setattr(client.settings, "openrouter_api_key", "test-only")
    assert client.endpoint() == (client.OPENROUTER_URL, "test-only")


async def test_whole_request_timeout_stops_keepalive_wait(monkeypatch):
    monkeypatch.setattr(client.settings, "openrouter_api_key", "test-only")
    monkeypatch.setattr(client.settings, "summary_timeout_sec", 0.01)

    async def never_finishes(*args, **kwargs):
        await asyncio.sleep(10)

    http = AsyncMock()
    http.post.side_effect = never_finishes
    manager = AsyncMock()
    manager.__aenter__.return_value = http
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: manager)
    with pytest.raises(client.LLMError, match="TimeoutError"):
        await client.complete("test", "test")


_OK = {"choices": [{"message": {"content": "안녕"}, "finish_reason": "stop"}], "usage": {}}


@pytest.mark.parametrize("configured, passed, expected", [
    (0.2, None, 0.2),  # 호출 쪽이 안 넘기면 설정값
    (0.2, 0.7, 0.7),  # 넘기면 그 값이 우선
    (None, 0.7, 0.7),
])
async def test_temperature_comes_from_settings_unless_passed(monkeypatch, configured, passed,
                                                             expected):
    monkeypatch.setattr(client.settings, "openrouter_api_key", "test-only")
    monkeypatch.setattr(client.settings, "llm_temperature", configured)
    http = _fake_http(monkeypatch, _OK)
    await client.complete("test", "test", temperature=passed)
    assert http.post.await_args.kwargs["json"]["temperature"] == expected


@pytest.mark.parametrize("provider", ["openrouter", "elice"])
async def test_no_temperature_omits_the_field(monkeypatch, provider):
    """luna 처럼 기본값(1)만 받는 모델은 필드가 있으면 400 이다. null 도 보내지 않는다."""
    _elice(monkeypatch)
    monkeypatch.setattr(client.settings, "llm_provider", provider)
    monkeypatch.setattr(client.settings, "openrouter_api_key", "test-only")
    monkeypatch.setattr(client.settings, "llm_temperature", None)
    http = _fake_http(monkeypatch, _OK)
    await client.complete("test", "test")
    assert "temperature" not in http.post.await_args.kwargs["json"]


@pytest.mark.parametrize("raw, expected", [("", None), ("  ", None), ("1", 1.0), ("0.2", 0.2)])
def test_blank_llm_temperature_env_means_none(monkeypatch, raw, expected):
    monkeypatch.setenv("LLM_TEMPERATURE", raw)
    assert Settings(_env_file=None).llm_temperature == expected


def test_llm_temperature_default_is_unchanged(monkeypatch):
    """이 줄이 없는 팀원의 .env 는 지금처럼 0.2 로 보낸다."""
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    assert Settings(_env_file=None).llm_temperature == 0.2


def test_elice_without_price_stops_before_calling(monkeypatch):
    """단가가 없으면 비용이 조용히 0 이 된다. 예전 USD 설정은 더 읽지 않는다고 알려준다."""
    _elice(monkeypatch, input_krw=None)
    with pytest.raises(RuntimeError, match="LLM_INPUT_KRW_PER_M"):
        client.endpoint()


async def test_usage_carries_currency(monkeypatch):
    monkeypatch.setattr(client.settings, "openrouter_api_key", "test-only")
    _fake_http(monkeypatch, {**_OK, "usage": {"cost": 0.01}})
    _, usage = await client.complete("test", "test")
    assert usage["cost_currency"] == "USD"


def test_format_cost():
    assert client.format_cost(5.115691, "KRW") == "₩5.12"
    assert client.format_cost(12345.6, "KRW") == "₩12,345.60"
    assert client.format_cost(0.0123, "USD") == "$0.0123"
