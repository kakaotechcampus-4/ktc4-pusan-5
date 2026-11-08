"""429 재시도가 한 곳에서만 일어나는지. 실제 complete() 를 쓰고 HTTP 만 바꿔 끼워 보낸 횟수를 센다.

complete() 는 429 를 기본으로 다시 보내지 않는다. 분류는 자기 대기(RATE_LIMIT_WAITS)로만 다시 보내고,
따로 기다리지 않는 호출부(리포트 요약·종목 보고서 생성·quote 고쳐 쓰기·요약 다시 쓰기)는
retry_rate_limited=True 로 예전과 같은 짧은 재시도(최대 2번, 2초·4초)를 그대로 받는다.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm import client
from app.services.analyst import summary as analyst_summary
from app.services.classification import llm as classification_llm
from app.services.stock_analysis import generate as gen
from app.services.stock_analysis import repair

MOCK_OK = {"choices": [{"message": {"content": "안녕"}, "finish_reason": "stop"}],
           "usage": {"cost": 0.01}}
FIXTURES = Path(__file__).parent / "fixtures" / "stock_analysis"


@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    """개인 .env 와 상관없이 OpenRouter·비스트리밍·기본 재시도 설정(2번, 2초부터)으로 고정한다."""
    monkeypatch.setattr(client.settings, "llm_provider", "openrouter")
    monkeypatch.setattr(client.settings, "openrouter_api_key", "test-only")
    monkeypatch.setattr(client.settings, "stock_analysis_stream", False)
    monkeypatch.setattr(client.settings, "llm_max_retries", 2)
    monkeypatch.setattr(client.settings, "llm_retry_backoff_sec", 2.0)
    monkeypatch.setattr(client.settings, "llm_retry_backoff_max_sec", 30.0)


@pytest.fixture
def waits(monkeypatch) -> AsyncMock:
    """client 와 분류가 같은 asyncio 모듈을 쓰므로 둘의 대기가 모두 여기 잡힌다. 실제로는 기다리지 않는다."""
    sleep = AsyncMock()
    monkeypatch.setattr(client.asyncio, "sleep", sleep)
    return sleep


def mock_status(code: int, headers: dict | None = None) -> client.httpx.Response:
    request = client.httpx.Request("POST", client.OPENROUTER_URL)
    return client.httpx.Response(code, request=request, text='{"error":"x"}', headers=headers)


def mock_ok(content: str = "안녕") -> MagicMock:
    response = MagicMock()
    response.json.return_value = {**MOCK_OK, "choices": [{"message": {"content": content},
                                                          "finish_reason": "stop"}]}
    return response


@pytest.fixture
def http(monkeypatch) -> AsyncMock:
    mock_http = AsyncMock()
    manager = AsyncMock()
    manager.__aenter__.return_value = mock_http
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: manager)
    return mock_http


def wait_seconds(waits: AsyncMock) -> list[float]:
    return [c.args[0] for c in waits.await_args_list]


# --- complete() ----------------------------------------------------------------

async def test_429_is_raised_after_one_request(http, waits):
    http.post.return_value = mock_status(429, {"retry-after": "7"})
    attempts: list[dict] = []
    with pytest.raises(client.LLMRateLimited, match="HTTP 429") as info:
        await client.complete("s", "u", attempts=attempts)
    assert http.post.await_count == 1 and waits.await_count == 0
    # 부르는 쪽이 대기를 정할 수 있게 병합 때 붙인 정보는 그대로 싣는다
    assert info.value.retryable and info.value.retry_after == 7.0 and info.value.kind == "http_429"
    assert [(a["attempt"], a["kind"], a["wait_sec"]) for a in attempts] == [(1, "http_429", None)]


@pytest.mark.parametrize("failure", [
    mock_status(500), mock_status(503), client.httpx.ConnectError("refused"),
])
async def test_5xx_and_connection_errors_are_still_retried(http, waits, failure):
    http.post.side_effect = [failure, failure, mock_ok()]
    text, _ = await client.complete("s", "u")
    assert text == "안녕" and http.post.await_count == 3
    assert wait_seconds(waits) == [2.0, 4.0]


async def test_5xx_then_429_stops_at_the_429(http, waits):
    http.post.side_effect = [mock_status(503), mock_status(429), mock_ok()]
    with pytest.raises(client.LLMRateLimited):
        await client.complete("s", "u")
    assert http.post.await_count == 2 and wait_seconds(waits) == [2.0]


async def test_opted_in_429_shares_the_5xx_budget(http, waits):
    """retry_rate_limited 는 예산을 하나로 쓴다. 5xx 와 429 가 섞여도 처음 1번 + 재시도 2번이다."""
    http.post.side_effect = [mock_status(503), mock_status(429), mock_status(429), mock_ok()]
    with pytest.raises(client.LLMRateLimited):
        await client.complete("s", "u", retry_rate_limited=True)
    assert http.post.await_count == 3 and wait_seconds(waits) == [2.0, 4.0]


async def test_opted_in_429_waits_for_longer_retry_after(http, waits):
    http.post.side_effect = [mock_status(429, {"retry-after": "7"}), mock_ok()]
    text, _ = await client.complete("s", "u", retry_rate_limited=True)
    assert text == "안녕" and wait_seconds(waits) == [7.0]


# --- 분류: 자기 대기로만 다시 보낸다 ------------------------------------------------

async def test_classification_step_sends_only_its_own_retries(http, waits):
    http.post.return_value = mock_status(429)
    result = await classification_llm.call("judge", "classification_events", "본문")
    expected = len(classification_llm.RATE_LIMIT_WAITS)
    assert result.error.startswith("judge: LLM 호출 실패: HTTP 429")
    # 예전에는 (2 + 1) × (3 + 1) = 12 번이었다
    assert http.post.await_count == expected + 1
    assert result.rate_limit_retries == expected
    # complete 의 2초·4초 대기는 없고, 분류 대기(5·20·60초를 1~1.5배로 흩음)만 있다
    seconds = wait_seconds(waits)
    assert len(seconds) == expected
    assert all(w <= s <= w * 1.5 for w, s in zip(classification_llm.RATE_LIMIT_WAITS, seconds, strict=True))


# --- 따로 기다리지 않는 호출부: 예전과 같은 횟수(1 + 2번, 2초·4초) --------------------

async def test_stock_analysis_generate_retries_429_as_before(http, waits):
    http.post.return_value = mock_status(429)
    cause = json.loads((FIXTURES / "sample_cause.json").read_text(encoding="utf-8"))
    wrapper = await gen.generate(cause, system="SYS", prompt_hash="abc", run_id="r1")
    assert wrapper["is_error"] and "HTTP 429" in wrapper["error"]
    assert http.post.await_count == 3 and wait_seconds(waits) == [2.0, 4.0]
    assert [(a["attempt"], a["kind"], a["wait_sec"]) for a in wrapper["llm_retries"]] == [
        (1, "http_429", 2.0), (2, "http_429", 4.0), (3, "http_429", None)]


@pytest.mark.parametrize("code", [429, 503])
async def test_analyst_summary_does_not_multiply_retries(http, waits, code):
    """요약의 재생성(MAX_ATTEMPTS)은 검증에 걸렸을 때만이다. 호출 실패는 complete 가 다시 보낸 것으로 끝낸다 —
    재생성까지 다시 부르면 3 × 3 = 9번이고, 시간 제한(summary_timeout_sec)이 시도마다 다시 걸린다."""
    http.post.return_value = mock_status(code)
    text, _, result = await analyst_summary.generate("분석 본문", "산업.pdf")
    assert text == "" and not result["ok"] and f"HTTP {code}" in result["problems"][0]
    assert result["attempt"] == 1
    assert http.post.await_count == 3 and wait_seconds(waits) == [2.0, 4.0]


def mock_source(quote: str) -> dict:
    return {"channel": "ch", "url": "https://t.me/ch/1", "datetime_kst": "2026-10-14T11:40:00+09:00",
            "quote": quote, "mention": "not_mentioned", "is_market_recap": False}


MOCK_PAYLOAD = {"messages": [{"channel": "ch", "url": "https://t.me/ch/1",
                              "datetime_kst": "2026-10-14T11:40:00+09:00", "mention": "not_mentioned",
                              "text": "미국의 전력망 보안 행정명령은 BESS를 규제 대상 장비로 명시"}]}


def mock_report() -> dict:
    """첫 factor 의 quote 가 본문에 없어 고쳐 쓰기 대상이다. main_cause 는 그 factor 를 뺐을 때 다시 쓴다."""
    bad = {"event": "행정명령", "detail": "", "stance": "bullish", "unconfirmed": False,
           "sources": [mock_source("본문에 없는 문장")], "links": [{"layer": "move", "strength": "partial"}]}
    good = {"event": "다른 사건", "detail": "", "stance": "bullish", "unconfirmed": False,
            "sources": [mock_source("BESS를 규제 대상 장비로")], "links": [{"layer": "move"}]}
    return {"factors": [bad, good], "summary": {"main_cause": "행정명령과 다른 사건 때문입니다."},
            "events": [{"event": "행정명령", "issue_ids": ["i1"], "factor": 0, "dup_channels": None,
                        "placed": "factors"},
                       {"event": "다른 사건", "issue_ids": ["i2"], "factor": 1, "dup_channels": None,
                        "placed": "factors"}]}


async def test_repair_quotes_retries_429_as_before(http, waits):
    http.post.return_value = mock_status(429)
    records = await repair.repair_quotes(mock_report(), MOCK_PAYLOAD, stream=False)
    assert len(records) == 1 and "HTTP 429" in records[0]["error"]
    assert http.post.await_count == 3 and wait_seconds(waits) == [2.0, 4.0]


async def test_rewrite_summary_retries_429_as_before(http, waits):
    report = mock_report()
    # 고쳐 쓴 quote 가 또 본문에 없어 factor 가 빠진다. 그다음 main_cause 다시 쓰기가 429 를 만난다
    http.post.side_effect = [mock_ok(json.dumps({"event": "행정명령", "detail": "",
                                                  "sources": [mock_source("여전히 없는 문장")]}))]
    records = await repair.repair_quotes(report, MOCK_PAYLOAD, stream=False)
    assert records[0]["result"] == "dropped"
    http.post.reset_mock(side_effect=True)
    http.post.return_value = mock_status(429)
    rewrite = await repair.rewrite_main_cause(report, records, stream=False)
    assert rewrite["result"] == "failed" and "HTTP 429" in rewrite["error"]
    assert http.post.await_count == 3 and wait_seconds(waits) == [2.0, 4.0]


# --- 스트림 중간 429: HTTP 429 와 같은 규칙 ------------------------------------------
# 헤더가 이미 200 인 뒤 error 이벤트로 오는 429 다. 리포트 요약(analyst)은 스트리밍하지 않아(complete 에 stream 을
# 넘기지 않는다) 여기서 보지 않는다.

def mock_sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False)


MOCK_STREAM_429 = [mock_sse({"choices": [{"delta": {"content": "가나"}}]}),
                   mock_sse({"error": {"code": 429, "message": "rate limited"}})]


def mock_stream_ok(content: str) -> list[str]:
    return [mock_sse({"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]}), "data: [DONE]"]


class MockStream:
    def __init__(self, lines: list[str]):
        self.lines, self.is_error = lines, False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self.lines:
            yield line


@pytest.fixture
def streams(monkeypatch) -> tuple[MagicMock, list[list[str]]]:
    """(가짜 http, 앞으로 줄 스트림들). 줄 것이 떨어지면 늘 스트림 중간 429 를 준다."""
    queued: list[list[str]] = []
    mock_http = MagicMock()
    mock_http.stream.side_effect = lambda *args, **kwargs: MockStream(queued.pop(0) if queued else MOCK_STREAM_429)
    manager = AsyncMock()
    manager.__aenter__.return_value = mock_http
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: manager)
    return mock_http, queued


async def test_classification_stream_429_waits_with_its_own_retries(streams, waits, monkeypatch):
    """분류는 Elice 일 때 스트리밍한다. 스트림 중간 429 도 complete 가 다시 보내지 않고 LLMRateLimited 로 올려,
    분류가 자기 대기(RATE_LIMIT_WAITS)로만 다시 부른다."""
    monkeypatch.setattr(client.settings, "llm_provider", "elice")
    monkeypatch.setattr(client.settings, "llm_base_url", "https://mlapi.run/mock/v1")
    monkeypatch.setattr(client.settings, "llm_api_key", "test-only")
    monkeypatch.setattr(client.settings, "llm_input_krw_per_m", 300.0)
    monkeypatch.setattr(client.settings, "llm_output_krw_per_m", 2500.0)
    mock_http, _ = streams
    result = await classification_llm.call("judge", "classification_events", "본문")
    expected = len(classification_llm.RATE_LIMIT_WAITS)
    assert result.error.startswith("judge: 스트림 중 오류")
    assert mock_http.stream.call_count == expected + 1 and result.rate_limit_retries == expected
    seconds = wait_seconds(waits)
    assert all(w <= s <= w * 1.5 for w, s in zip(classification_llm.RATE_LIMIT_WAITS, seconds, strict=True))


async def test_stock_analysis_generate_retries_stream_429(streams, waits, monkeypatch):
    monkeypatch.setattr(client.settings, "stock_analysis_stream", True)
    mock_http, _ = streams
    cause = json.loads((FIXTURES / "sample_cause.json").read_text(encoding="utf-8"))
    wrapper = await gen.generate(cause, system="SYS", prompt_hash="abc", run_id="r1")
    assert wrapper["is_error"] and wrapper["error_code"] == "STREAM_INTERRUPTED"
    assert mock_http.stream.call_count == 3 and wait_seconds(waits) == [2.0, 4.0]
    assert [(a["kind"], a["wait_sec"]) for a in wrapper["llm_retries"]] == [
        ("stream", 2.0), ("stream", 4.0), ("stream", None)]
    # 끊긴 스트림이라 받은 길이가 stream_interruptions 에 남는다
    assert [s["partial_chars"] for s in wrapper["stream_interruptions"]] == [2, 2, 2]


async def test_stock_analysis_generate_recovers_after_stream_429(streams, waits, monkeypatch):
    monkeypatch.setattr(client.settings, "stock_analysis_stream", True)
    mock_http, queued = streams
    queued += [MOCK_STREAM_429, mock_stream_ok(json.dumps({"ticker": "999990"}))]
    cause = json.loads((FIXTURES / "sample_cause.json").read_text(encoding="utf-8"))
    wrapper = await gen.generate(cause, system="SYS", prompt_hash="abc", run_id="r1")
    assert wrapper["error_code"] != "STREAM_INTERRUPTED" and wrapper["json_status"] is not None
    assert mock_http.stream.call_count >= 2 and wait_seconds(waits)[:1] == [2.0]
    assert wrapper["llm_retries"][0]["kind"] == "stream"


async def test_repair_quotes_retries_stream_429(streams, waits):
    mock_http, _ = streams
    records = await repair.repair_quotes(mock_report(), MOCK_PAYLOAD, stream=True)
    assert len(records) == 1 and "스트림 중 오류" in records[0]["error"]
    assert mock_http.stream.call_count == 3 and wait_seconds(waits) == [2.0, 4.0]


async def test_rewrite_summary_retries_stream_429(streams, waits):
    mock_http, queued = streams
    report = mock_report()
    # 고쳐 쓴 quote 가 또 본문에 없어 factor 가 빠진다. 그다음 main_cause 다시 쓰기가 스트림 중간 429 를 만난다
    queued.append(mock_stream_ok(json.dumps({"event": "행정명령", "detail": "",
                                             "sources": [mock_source("여전히 없는 문장")]}, ensure_ascii=False)))
    records = await repair.repair_quotes(report, MOCK_PAYLOAD, stream=True)
    assert records[0]["result"] == "dropped" and mock_http.stream.call_count == 1
    rewrite = await repair.rewrite_main_cause(report, records, stream=True)
    assert rewrite["result"] == "failed" and "스트림 중 오류" in rewrite["error"]
    assert mock_http.stream.call_count == 1 + 3 and wait_seconds(waits) == [2.0, 4.0]
