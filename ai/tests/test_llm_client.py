"""토큰 추정치보다 프로바이더 사용료를 우선하고 응답 중단 사유를 보존한다."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm import client


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
