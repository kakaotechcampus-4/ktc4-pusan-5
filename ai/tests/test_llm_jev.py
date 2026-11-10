"""Jev 판단 호출: 설정 확인, 요청 모양, 응답 검사, 비용. 실제 API 는 부르지 않는다."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm import jev
from app.llm.client import LLMError, LLMRateLimited

URL = "https://mlapi.run/jev-test/v1/decisions"
QUESTIONS = {"target": {"type": "choice", "instructions": "어느 회사인가?",
                        "criteria": {"005930": "삼성전자", "none": "목록에 없음"}}}


@pytest.fixture(autouse=True)
def jev_settings(monkeypatch):
    """settings 는 개발자 각자의 ai/.env 를 읽는다. 그 값에 따라 결과가 달라지지 않게 고정한다."""
    monkeypatch.setattr(jev.settings, "jev_url", URL)
    monkeypatch.setattr(jev.settings, "jev_api_key", "jev-only")
    monkeypatch.setattr(jev.settings, "llm_api_key", "llm-only")
    monkeypatch.setattr(jev.settings, "jev_model", "typesafe/jev-1.14")
    monkeypatch.setattr(jev.settings, "jev_input_krw_per_m", 59.0)


def _fake_http(monkeypatch, body: object = None, status: int | None = None) -> AsyncMock:
    http = AsyncMock()
    if status is None:
        response = MagicMock()
        response.json.return_value = body
        http.post.return_value = response
    else:
        request = jev.httpx.Request("POST", URL)
        http.post.return_value = jev.httpx.Response(status, request=request, text=body or "")
    manager = AsyncMock()
    manager.__aenter__.return_value = http
    monkeypatch.setattr(jev.httpx, "AsyncClient", lambda **kwargs: manager)
    return http


async def test_sends_state_and_questions_to_decisions(monkeypatch):
    http = _fake_http(monkeypatch, {
        "answers": {"target": {"type": "choice", "choice": "005930", "confidence": 0.97}},
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0},
    })
    answers, usage = await jev.decide({"mention": "삼성"}, QUESTIONS)

    assert http.post.await_args.args[0] == URL
    sent = http.post.await_args.kwargs["json"]
    assert sent == {"model": "typesafe/jev-1.14", "state": {"mention": "삼성"},
                    "questions": QUESTIONS}
    # 채팅 API 의 매개변수가 섞이면 안 된다. 스트리밍도 지원하지 않는다
    assert not {"messages", "stream", "max_completion_tokens"} & sent.keys()
    assert http.post.await_args.kwargs["headers"] == {"Authorization": "Bearer jev-only"}
    assert answers["target"]["choice"] == "005930"
    assert usage["model"] == "typesafe/jev-1.14" and usage["cost_currency"] == "KRW"
    # 입력 토큰만 과금된다
    assert jev.cost(usage) == pytest.approx(59.0)


async def test_model_can_be_given_per_call(monkeypatch):
    http = _fake_http(monkeypatch, {"answers": {}, "usage": {}})
    _, usage = await jev.decide("본문", QUESTIONS, model="typesafe/jev-1.13")
    assert http.post.await_args.kwargs["json"]["model"] == "typesafe/jev-1.13"
    assert usage["model"] == "typesafe/jev-1.13"


async def test_falls_back_to_llm_key_when_jev_key_is_blank(monkeypatch):
    monkeypatch.setattr(jev.settings, "jev_api_key", "  ")
    http = _fake_http(monkeypatch, {"answers": {}, "usage": {}})
    await jev.decide("본문", QUESTIONS)
    assert http.post.await_args.kwargs["headers"] == {"Authorization": "Bearer llm-only"}


@pytest.mark.parametrize("field, value, named", [
    ("jev_url", None, "JEV_URL"),
    ("jev_input_krw_per_m", None, "JEV_INPUT_KRW_PER_M"),
])
def test_missing_setting_stops_before_calling(monkeypatch, field, value, named):
    monkeypatch.setattr(jev.settings, field, value)
    with pytest.raises(RuntimeError, match=named):
        jev.endpoint()


def test_missing_both_keys_stops_before_calling(monkeypatch):
    monkeypatch.setattr(jev.settings, "jev_api_key", None)
    monkeypatch.setattr(jev.settings, "llm_api_key", None)
    with pytest.raises(RuntimeError, match="JEV_API_KEY"):
        jev.endpoint()


async def test_empty_questions_are_refused_before_calling(monkeypatch):
    http = _fake_http(monkeypatch, {"answers": {}})
    with pytest.raises(ValueError):
        await jev.decide("본문", {})
    http.post.assert_not_awaited()


@pytest.mark.parametrize("body", [
    [], {"usage": {}}, {"answers": {"target": "005930"}}, {"answers": {}, "usage": "100"},
])
async def test_unexpected_shape_is_llm_error(monkeypatch, body):
    """모양이 다른 응답이 AttributeError 로 새면 배치 전체가 멈춘다."""
    _fake_http(monkeypatch, body)
    with pytest.raises(LLMError, match="Jev 응답 형식 오류"):
        await jev.decide("본문", QUESTIONS)


async def test_only_429_is_rate_limited_and_key_is_redacted(monkeypatch):
    _fake_http(monkeypatch, '{"error":"slow down jev-only"}', status=429)
    with pytest.raises(LLMRateLimited, match=r"HTTP 429") as caught:
        await jev.decide("본문", QUESTIONS)
    assert "jev-only" not in str(caught.value)

    _fake_http(monkeypatch, "bad request", status=400)
    with pytest.raises(LLMError) as caught:
        await jev.decide("본문", QUESTIONS)
    assert not isinstance(caught.value, LLMRateLimited)


def test_cost_without_token_count_is_zero():
    assert jev.cost({}) == 0.0
