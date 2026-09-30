"""③ 생성 · ④ 래핑. complete() 를 바꿔 끼워 실제 API 를 부르지 않는다."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.llm.client import LLMError
from app.repositories.stock_move_analysis import parse_wrapper
from app.services.stock_analysis import generate as gen

FIXTURES = Path(__file__).parent / "fixtures" / "stock_analysis"
CAUSE = json.loads((FIXTURES / "sample_cause.json").read_text(encoding="utf-8"))
REPORT = {"ticker": "999990", "verdict": "no_clear_cause"}
REPORT_TEXT = json.dumps(REPORT, ensure_ascii=False)
USAGE = {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.0123, "finish_reason": "stop"}


@pytest.fixture(autouse=True)
def openrouter(monkeypatch):
    """개인 ai/.env 의 LLM_PROVIDER 가 통화를 바꾸지 않게 고정한다."""
    monkeypatch.setattr(gen.settings, "llm_provider", "openrouter")


@pytest.fixture
def fake_complete(monkeypatch):
    mock = AsyncMock(side_effect=AssertionError("응답을 정해 두지 않았다"))
    monkeypatch.setattr(gen, "complete", mock)
    return mock


async def run(fake, text=None, exc=None):
    fake.side_effect = exc
    fake.return_value = (text, USAGE)
    return await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")


async def test_clean_response(fake_complete):
    w = await run(fake_complete, REPORT_TEXT)
    assert w["json_status"] == "clean"
    assert w["final_text"] == REPORT_TEXT
    assert w["raw_text"] is None
    assert not w["is_error"] and not w["asked_question"]
    assert w["cost"] == pytest.approx(0.0123)
    assert w["cost_currency"] == "USD"
    assert w["usage"]["prompt_tokens"] == 1000
    assert w["prompt_sha256"] == "abc"
    # 스키마 검사 결과가 래퍼에 들어간다
    assert "SCHEMA_MISSING: summary" in w["schema_problems"]


async def test_prompt_and_input_are_sent(fake_complete):
    await run(fake_complete, REPORT_TEXT)
    system, user = fake_complete.call_args.args
    assert system == "SYS"
    assert json.loads(user) == CAUSE


@pytest.mark.parametrize("text", [
    f"```json\n{REPORT_TEXT}\n```",
    f"아래와 같이 정리했습니다.\n{REPORT_TEXT}",
    f"{REPORT_TEXT}\n\n위 보고서는 제공된 메시지만 근거로 했습니다.",
])
async def test_stripped_response_keeps_json_in_final_text(fake_complete, text):
    """final_text 는 벗겨낸 JSON 이라 parse_wrapper 가 열 수 있다. 원문은 raw_text 에."""
    w = await run(fake_complete, text)
    assert w["json_status"] == "stripped"
    assert json.loads(w["final_text"]) == REPORT
    assert w["raw_text"] == text
    parsed = parse_wrapper(w)
    assert parsed.analysis == REPORT
    # 손을 댄 회차라 적재는 schema_violation 으로 표시한다
    assert parsed.parse_status == "schema_violation"


async def test_invalid_response(fake_complete):
    w = await run(fake_complete, "보고서를 쓰지 못했습니다.")
    assert w["json_status"] == "invalid"
    assert w["final_text"] == "보고서를 쓰지 못했습니다."
    assert not w["asked_question"] and not w["is_error"]
    assert parse_wrapper(w).parse_status == "parse_failed"


@pytest.mark.parametrize("text", ["어느 기준 시각으로 작성할까요?", "종목코드를 알려주시겠어요？"])
async def test_invalid_response_ending_with_question(fake_complete, text):
    w = await run(fake_complete, text)
    assert w["json_status"] == "invalid"
    assert w["asked_question"] is True


async def test_question_mark_inside_valid_json_is_not_asking(fake_complete):
    w = await run(fake_complete, '{"summary": "왜 올랐을까?"}')
    assert w["json_status"] == "clean" and w["asked_question"] is False


async def test_empty_response_is_error(fake_complete):
    w = await run(fake_complete, "")
    assert w["is_error"] is True
    assert w["error_code"] == "EMPTY_RESPONSE"
    assert "finish_reason=stop" in w["error"]
    # 비용은 나갔으므로 남긴다
    assert w["cost"] == pytest.approx(0.0123)


async def test_llm_error_is_recorded_not_raised(fake_complete):
    w = await run(fake_complete, exc=LLMError("LLM 호출 실패: HTTP 429 too many"))
    assert w["is_error"] is True
    assert w["error_code"] == "LLM_ERROR"
    assert "HTTP 429" in w["error"]
    assert w["json_status"] is None and w["final_text"] == ""
    assert parse_wrapper(w).parse_status == "parse_failed"


def test_report_of_only_opens_readable_wrappers():
    assert gen.report_of({"is_error": False, "json_status": "clean", "final_text": "{}"}) == {}
    assert gen.report_of({"is_error": False, "json_status": "invalid", "final_text": "x"}) is None
    assert gen.report_of({"is_error": True, "json_status": "clean", "final_text": "{}"}) is None


def test_make_run_id():
    assert gen.make_run_id(CAUSE) == "솔마루전자-2026-09-18-1530__r1"
    assert gen.make_run_id({**CAUSE, "cutoff": "11:05"}, 2) == "솔마루전자-2026-09-18-1105__r2"
    # 파일명에 못 쓰는 글자는 바꾼다
    assert gen.make_run_id({**CAUSE, "stock": "A/B 전자"}).startswith("A_B_전자-")


def test_check_input():
    assert gen.check_input(CAUSE) == []
    assert gen.check_input([]) == ["입력이 객체가 아니다: list"]
    broken = {k: v for k, v in CAUSE.items() if k != "code"} | {"change_pct": "-4.2"}
    assert gen.check_input(broken) == ["code 가 없다", "change_pct 는 숫자여야 한다: '-4.2'"]


def test_prompt_sha256_is_file_hash():
    import hashlib

    path = gen.PROMPT_DIR / "stock_analysis_system.md"
    assert gen.prompt_sha256() == hashlib.sha256(path.read_bytes()).hexdigest()
