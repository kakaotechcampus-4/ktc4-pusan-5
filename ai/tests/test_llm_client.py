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
    assert client.cost_usd({"cost": 0.123, "prompt_tokens": 1000}) == 0.123
    assert client.cost_usd({"cost": 0.0, "prompt_tokens": 1000}) == 0.0
    assert client.cost_usd({"prompt_tokens": 1000}) == pytest.approx(0.00006)


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
    monkeypatch.setattr(client.settings, "llm_provider", "elice")
    monkeypatch.setattr(client.settings, "llm_base_url", "https://mlapi.run/abc/v1/")
    monkeypatch.setattr(client.settings, "llm_api_key", "test-only")
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
    # 응답에 비용이 없으니 단가로 계산한다. 기본 단가 $0.3 + $2.5
    assert client.cost_usd(usage) == pytest.approx(2.8)


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
