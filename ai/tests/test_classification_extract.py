"""사건 추출 한 회차. LLM 을 부르지 않는다 — complete 를 바꿔 끼워 상태 처리만 본다."""

import json
from unittest.mock import AsyncMock

from app.llm.client import LLMError, load_prompt
from app.services.classification import extract as extract_service
from app.services.classification.extract import (
    MAX_INPUT_CHARS,
    PROMPT_NAME,
    build_user_message,
    extract_events,
)

BODY = "D램 가격이 급등했다. 회사는 3분기 실적 개선을 예고했다."
TITLE = "SK하이닉스, D램 가격 급등에 실적 기대"
OK_RESPONSE = json.dumps({"events": [
    {"scope": "industry", "role": "cause", "tense": "past", "sentences": [1],
     "mentions": ["D램"]},
    {"scope": "company", "role": "outlook", "tense": "future", "sentences": [2],
     "mentions": ["SK하이닉스"]},
]}, ensure_ascii=False)


def fake_complete(monkeypatch, *, text: str = OK_RESPONSE, usage: dict | None = None,
                  error: Exception | None = None) -> AsyncMock:
    mock = AsyncMock(side_effect=error) if error else AsyncMock(
        return_value=(text, usage or {"finish_reason": "stop"}))
    monkeypatch.setattr(extract_service, "complete", mock)
    return mock


def test_prompt_file_exists() -> None:
    assert "events" in load_prompt(PROMPT_NAME)


def test_user_message_numbers_body_but_not_title() -> None:
    message = build_user_message(TITLE, ["가.", "나."])
    assert message == f"[제목] {TITLE}\n\n[본문]\n[1] 가.\n[2] 나."


async def test_ok_run_records_versions_and_events(monkeypatch) -> None:
    complete = fake_complete(monkeypatch)
    run = await extract_events(BODY, TITLE)
    assert run.status == "ok"
    assert run.splitter_version == "v1" and run.sentence_count == 2
    assert run.prompt_sha256 and run.input_sha256 and run.model
    assert [e.scope for e in run.events] == ["industry", "company"]
    sent_user = complete.await_args.args[1]
    assert "[1] D램 가격이 급등했다." in sent_user


async def test_mention_only_in_title_is_kept(monkeypatch) -> None:
    """본문은 '회사는' 이라고만 쓰고 이름은 제목에 있다."""
    fake_complete(monkeypatch)
    run = await extract_events(BODY, TITLE)
    assert run.events[1].mentions == ("SK하이닉스",)
    assert run.dropped_mentions == []


async def test_empty_event_list_is_ok(monkeypatch) -> None:
    """이유가 될 내용이 없는 기사라는 판단이다. 실패가 아니다."""
    fake_complete(monkeypatch, text='{"events": []}')
    run = await extract_events(BODY, TITLE)
    assert run.status == "ok" and run.events == []


async def test_no_body_does_not_call_llm(monkeypatch) -> None:
    complete = fake_complete(monkeypatch)
    assert (await extract_events("  ", TITLE)).status == "no_body"
    complete.assert_not_awaited()


async def test_too_long_body_is_skipped(monkeypatch) -> None:
    complete = fake_complete(monkeypatch)
    run = await extract_events("가" * (MAX_INPUT_CHARS + 1), TITLE)
    assert run.status == "skipped"
    complete.assert_not_awaited()


async def test_llm_error_is_failed(monkeypatch) -> None:
    fake_complete(monkeypatch, error=LLMError("LLM 호출 실패: HTTP 429"))
    run = await extract_events(BODY, TITLE)
    assert run.status == "failed" and "429" in run.error
    assert run.raw_response is None


async def test_broken_response_is_failed_but_kept(monkeypatch) -> None:
    """형식이 깨진 응답도 원문을 남긴다. 왜 깨졌는지는 그걸 봐야 안다."""
    fake_complete(monkeypatch, text='{"events": [', usage={"finish_reason": "length"})
    run = await extract_events(BODY, TITLE)
    assert run.status == "failed"
    assert run.raw_response == '{"events": ['
    assert "finish_reason=length" in run.error


async def test_title_counts_toward_input_limit(monkeypatch) -> None:
    """제목도 같이 보낸다. 본문만 세면 긴 제목이 상한을 우회한다."""
    complete = fake_complete(monkeypatch)
    assert (await extract_events(BODY, "x" * MAX_INPUT_CHARS)).status == "skipped"
    complete.assert_not_awaited()


async def test_complete_json_is_ok_even_if_finish_reason_is_length(monkeypatch) -> None:
    """잘린 응답은 JSON 이 깨져 검사에서 걸린다. 끝까지 읽힌 JSON 을 finish_reason 만 보고 버리지 않는다."""
    fake_complete(monkeypatch, text=OK_RESPONSE, usage={"finish_reason": "length"})
    run = await extract_events(BODY, TITLE)
    assert run.status == "ok" and len(run.events) == 2
