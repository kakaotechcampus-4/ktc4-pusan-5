"""자료 하나 분류(①~④). LLM 을 부르지 않는다 — complete 를 바꿔 끼워 단계 연결과 상태 처리만 본다."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.llm.client import LLMError, load_prompt
from app.services.classification import llm
from app.services.classification.basis import load_basis
from app.services.classification.extract import MAX_INPUT_CHARS, PROMPT_NAME, build_user_message
from app.services.classification.pipeline import classify

BASIS = load_basis(Path(__file__).parent / "fixtures" / "mock_classification_basis.json")
TITLE = "SK하이닉스, D램 가격 급등에 실적 기대"
BODY = "D램 가격이 급등했다. 회사는 3분기 실적 개선을 예고했다. 미국 금리가 내렸다."
EVENTS = {"events": [
    {"scope": "industry", "role": "cause", "tense": "past", "sentences": [1], "mentions": ["D램"]},
    {"scope": "company", "role": "outlook", "tense": "future", "sentences": [2],
     "mentions": ["SK하이닉스"]},
    {"scope": "macro", "role": "cause", "tense": "past", "sentences": [3], "mentions": ["미국 금리"]},
]}
JUDGMENTS = {"judgments": [
    {"event": 1, "stock": "000660", "label": "DIRECT", "reason": "D램 생산"},
    {"event": 1, "stock": "005930", "label": "DIRECT", "reason": "D램 생산"},
    {"event": 1, "stock": "402340", "label": "DIRECT", "reason": "지분"},  # 상한에 걸려 내려간다
    {"event": 2, "stock": "000660", "label": "DIRECT", "reason": "회사 전망"},
    {"event": 2, "stock": "402340", "label": "INDIRECT_CONTEXT", "reason": "지분"},
]}


def fake_llm(monkeypatch, *, extract=EVENTS, judge=JUDGMENTS, link=None, usage=None,
             error_step: str | None = None) -> AsyncMock:
    """보낸 사용자 메시지로 단계를 가려 그 단계의 응답을 준다."""
    replies = {"extract": extract, "judge": judge, "link": link or {"links": []}}

    async def complete(system, user, **kwargs):
        step = ("judge" if "# 판정할 사건" in user else "link" if "# 고를 표기" in user else "extract")
        if step == error_step:
            raise LLMError("LLM 호출 실패: HTTP 429")
        reply = replies[step]
        return (reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False),
                usage or {"finish_reason": "stop", "cost": 0.001})

    mock = AsyncMock(side_effect=complete)
    monkeypatch.setattr(llm, "complete", mock)
    return mock


def steps_called(mock: AsyncMock) -> list[str]:
    users = [call.args[1] for call in mock.await_args_list]
    return ["judge" if "# 판정할 사건" in u else "link" if "# 고를 표기" in u else "extract"
            for u in users]


def test_prompt_files_exist() -> None:
    assert "events" in load_prompt(PROMPT_NAME)
    assert "judgments" in load_prompt("classification_judge")
    assert "links" in load_prompt("classification_link")


def test_user_message_numbers_body_but_not_title() -> None:
    assert build_user_message(TITLE, ["가.", "나."]) == f"[제목] {TITLE}\n\n[본문]\n[1] 가.\n[2] 나."


async def test_ok_run_goes_through_every_step(monkeypatch) -> None:
    mock = fake_llm(monkeypatch)
    result = await classify(TITLE, BODY, BASIS)
    assert result.status == "ok", result.error
    assert steps_called(mock) == ["extract", "judge"]  # 모두 사전에 걸려 link 는 부르지 않는다
    assert result.sentence_count == 3 and result.splitter_version == "v1" and result.input_sha256
    industry, _, macro = result.events
    assert {j.stock_code: j.label for j in industry.judgments} == {
        "005930": "DIRECT", "000660": "DIRECT", "402340": "INDIRECT_CONTEXT"}
    assert result.judge_fixes["direct_lowered"] == 1
    assert macro.candidates == [] and macro.judgments == []
    assert result.direct_stocks() == {"000660", "005930"}
    assert set(result.usage) == {"extract", "judge"}
    assert result.usage["judge"]["model"] and result.cost == pytest.approx(0.002)


async def test_models_can_differ_by_step(monkeypatch) -> None:
    mock = fake_llm(monkeypatch)
    result = await classify(TITLE, BODY, BASIS, models={"extract": "small", "judge": "large"})
    assert [call.kwargs["model"] for call in mock.await_args_list] == ["small", "large"]
    assert result.usage["extract"]["model"] == "small" and result.usage["judge"]["model"] == "large"


async def test_unknown_mention_goes_to_llm_code_choice(monkeypatch) -> None:
    extract = {"events": [{"scope": "industry", "role": "cause", "tense": "past",
                           "sentences": [1], "mentions": ["D램 가격"]}]}
    body = "D램 가격이 급등했다."
    mock = fake_llm(monkeypatch, extract=extract,
                    link={"links": [{"event": 1, "mention": "D램 가격", "code": "memory"}]},
                    judge={"judgments": []})
    result = await classify("", body, BASIS)
    assert steps_called(mock) == ["extract", "link", "judge"]
    assert result.events[0].links[0].linked_by == "llm_code"
    assert result.events[0].unresolved == []
    assert result.judge_fixes["missing_filled"] == 3  # 판정이 비어 후보 셋 모두 UNKNOWN


async def test_no_candidates_means_no_judge_call(monkeypatch) -> None:
    mock = fake_llm(monkeypatch, extract={"events": [
        {"scope": "market", "role": "cause", "tense": "past", "sentences": [3], "mentions": []}]})
    result = await classify(TITLE, BODY, BASIS)
    assert result.status == "ok" and steps_called(mock) == ["extract"]
    assert "judge" not in result.calls


async def test_empty_event_list_is_ok(monkeypatch) -> None:
    """이유가 될 내용이 없는 자료라는 판단이다. 실패가 아니다."""
    fake_llm(monkeypatch, extract={"events": []})
    result = await classify(TITLE, BODY, BASIS)
    assert result.status == "ok" and result.events == []


async def test_no_body_and_too_long_do_not_call_llm(monkeypatch) -> None:
    mock = fake_llm(monkeypatch)
    assert (await classify(TITLE, "  ", BASIS)).status == "no_body"
    assert (await classify(TITLE, None, BASIS)).status == "no_body"
    # 제목도 같이 센다. 본문만 세면 긴 제목이 상한을 우회한다
    assert (await classify("x" * MAX_INPUT_CHARS, BODY, BASIS)).status == "skipped"
    mock.assert_not_awaited()


@pytest.mark.parametrize("step", ["extract", "judge"])
async def test_llm_error_fails_the_run(monkeypatch, step: str) -> None:
    fake_llm(monkeypatch, error_step=step)
    result = await classify(TITLE, BODY, BASIS)
    assert result.status == "failed" and "429" in result.error and result.error.startswith(step)


async def test_broken_extraction_is_failed_but_kept(monkeypatch) -> None:
    """형식이 깨진 응답도 원문을 남긴다. 왜 깨졌는지는 그걸 봐야 안다."""
    fake_llm(monkeypatch, extract='{"events": [', usage={"finish_reason": "length"})
    result = await classify(TITLE, BODY, BASIS)
    assert result.status == "failed" and "finish_reason=length" in result.error
    assert result.calls["extract"].raw_response == '{"events": ['


async def test_broken_judgment_is_failed_but_kept(monkeypatch) -> None:
    fake_llm(monkeypatch, judge="판정을 못 했습니다")
    result = await classify(TITLE, BODY, BASIS)
    assert result.status == "failed" and result.error.startswith("judge")
    assert result.calls["judge"].raw_response == "판정을 못 했습니다"


async def test_mention_only_in_title_is_kept(monkeypatch) -> None:
    """본문은 '회사는' 이라고만 쓰고 이름은 제목에 있다."""
    fake_llm(monkeypatch)
    result = await classify(TITLE, BODY, BASIS)
    assert result.events[1].event.mentions == ("SK하이닉스",)
    assert result.dropped_mentions == []
