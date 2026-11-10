"""③ 생성 · ④ 래핑. complete() 를 바꿔 끼워 실제 API 를 부르지 않는다."""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.llm.client import LLMError, LLMTimeout, StreamInterrupted
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
    # 메시지를 세 칸으로 나누고 market 에 러너가 계산한 칸을 더해 보낸다. move_case 는 보내지 않는다.
    # 원본 dict 는 그대로다
    sent = {k: v for k, v in CAUSE.items() if k != "messages"}
    numbered = [{"id": f"m{k + 1}", **m} for k, m in enumerate(CAUSE["messages"])]  # 근거 칸에 m1… id
    assert json.loads(user) == {**sent, "sector": None, "main_cause_sentences": 3,
                                "display_as_of": "15:30", "as_of_phrase": "오후 3시 30분 장 마감 기준",
                                "messages": numbered, "market_context": [], "flow": [],
                                "market": {**CAUSE["market"], "judge_layers": {"move": True, "relative": True},
                                           "common_move": False, "move_strength_cap": None, "market_led": False,
                                           "move_comparison": "더",
                                           "universe_weight": None}}
    assert "judge_layers" not in CAUSE["market"]


async def test_move_case_is_recomputed_and_kept_in_wrapper(fake_complete):
    fake_complete.side_effect = None
    fake_complete.return_value = (REPORT_TEXT, USAGE)
    stale = {**CAUSE, "market": {**CAUSE["market"], "excess_pct": 0.3, "move_case": "normal"}}
    w = await gen.generate(stale, system="SYS", prompt_hash="abc", run_id="r1")
    # 입력에 적힌 move_case 를 믿지 않고 다시 계산해 래퍼에만 남긴다. 모델에는 보내지 않는다
    assert "move_case" not in json.loads(fake_complete.call_args.args[1])["market"]
    assert w["move_case"] == "flat"


async def test_null_market_gets_no_move_case(fake_complete):
    fake_complete.side_effect = None
    fake_complete.return_value = (REPORT_TEXT, USAGE)
    w = await gen.generate({**CAUSE, "market": None}, system="SYS", prompt_hash="abc", run_id="r1")
    assert json.loads(fake_complete.call_args.args[1])["market"] is None
    assert w["move_case"] is None


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


# 프록시가 비스트리밍 출력을 2000 에서 자른 날의 모양. 추론에 예산을 다 써서 본문이 비었다.
TRUNCATED_USAGE = {"prompt_tokens": 80000, "completion_tokens": 2000, "finish_reason": "length",
                   "completion_tokens_details": {"reasoning_tokens": 2000}}


@pytest.mark.parametrize("text, empty", [("", True), ('{"ticker": "999990", "summ', False)])
async def test_length_is_output_truncated_not_empty(fake_complete, text, empty):
    fake_complete.side_effect = None
    fake_complete.return_value = (text, TRUNCATED_USAGE)
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert w["is_error"] is True and w["error_code"] == "OUTPUT_TRUNCATED"
    assert w["json_status"] == "invalid" and w["final_text"] == ""
    assert w["truncation"] == {"body_empty": empty, "body_chars": len(text),
                               "reasoning_tokens": 2000, "completion_tokens": 2000}
    # 잘린 본문은 원문 칸에 남는다. 열어 보지 않는다
    assert w["raw_text"] == (text or None)
    assert "reasoning_tokens=2000" in w["error"]
    # 같은 설정으로 다시 보내지 않는다
    assert fake_complete.await_count == 1


async def test_wrapper_splits_input_tokens_and_marks_cost_basis(fake_complete, monkeypatch):
    """캐시 쓰기가 있는 첫 호출. prompt_tokens 에 쓰기 할증(25%)이 섞여 있다."""
    monkeypatch.setattr(gen.settings, "llm_provider", "elice")
    monkeypatch.setattr(gen.settings, "llm_input_krw_per_m", 1000.0)
    monkeypatch.setattr(gen.settings, "llm_output_krw_per_m", 8000.0)
    monkeypatch.setattr(gen.settings, "llm_cache_read_krw_per_m", 100.0)
    monkeypatch.setattr(gen.settings, "llm_cache_write_krw_per_m", None)
    usage = {"prompt_tokens": 9159, "completion_tokens": 1000, "finish_reason": "stop",
             "prompt_tokens_details": {"cached_tokens": 8702, "cache_write_tokens": 363}}
    fake_complete.side_effect = None
    fake_complete.return_value = (REPORT_TEXT, usage)
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert w["input_tokens"] == {"reported": 9159, "total": 9068, "cache_read": 8702,
                                 "cache_write": 363, "uncached": 3}
    assert w["cost_basis"] == "token_rates"
    # 쓰기 단가가 비어 입력 단가로 계산한다. 무엇을 썼는지 남는다
    assert w["cost_rates"] == {"input": 1000.0, "cache_read": 100.0, "cache_write": 1000.0,
                               "output": 8000.0}
    assert w["cost"] == pytest.approx((3 * 1000 + 8702 * 100 + 363 * 1000 + 1000 * 8000) / 1e6)
    assert w["cost_currency"] == "KRW"


async def test_provider_cost_is_marked(fake_complete):
    w = await run(fake_complete, REPORT_TEXT)
    assert w["cost_basis"] == "provider" and w["cost_rates"] is None
    assert w["input_tokens"]["total"] == 1000 and w["input_tokens"]["uncached"] == 1000


async def test_wrapper_records_request_settings(fake_complete, monkeypatch):
    """Elice 면 기본으로 스트리밍이다. 상한·추론 강도를 complete 에 명시해 넘기고 래퍼에 남긴다."""
    monkeypatch.setattr(gen.settings, "llm_provider", "elice")
    monkeypatch.setattr(gen.settings, "stock_analysis_stream", None)
    monkeypatch.setattr(gen.settings, "summary_max_tokens", 8000)
    monkeypatch.setattr(gen.settings, "summary_reasoning_effort", "low")
    w = await run(fake_complete, REPORT_TEXT)
    kwargs = fake_complete.await_args.kwargs
    assert (kwargs["max_tokens"], kwargs["stream"]) == (8000, True)
    assert (w["stream"], w["max_completion_tokens"], w["reasoning_effort"]) == (True, 8000, "low")
    assert w["stream_interruptions"] == [] and w["llm_retries"] == []


async def test_openrouter_does_not_stream_by_default(fake_complete):
    w = await run(fake_complete, REPORT_TEXT)
    assert fake_complete.await_args.kwargs["stream"] is False and w["stream"] is False


def _attempt(n, kind, error, partial=None, elapsed=1.0):
    """client.complete 가 attempts 에 남기는 실패한 시도 하나."""
    return {"attempt": n, "kind": kind, "error": error, "elapsed_sec": elapsed, "wait_sec": 2.0,
            "partial_chars": partial}


def _complete_after(records, outcome):
    """client.complete 흉내. 재시도는 complete 안에서 끝났고, 그 기록을 attempts 에 남긴 뒤 결과를 낸다."""
    async def fake(*args, attempts=None, **kwargs):
        attempts.extend(records)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    return fake


async def test_retries_recorded_by_client_move_into_wrapper(fake_complete):
    """재시도는 complete 가 한다. generate 는 한 번만 부르고 그 시도 기록을 래퍼로 옮긴다."""
    fake_complete.side_effect = _complete_after(
        [_attempt(1, "stream", "스트림이 끊겼다: ReadError", 120)], (REPORT_TEXT, USAGE))
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 1
    assert not w["is_error"] and w["json_status"] == "clean"
    # 끊긴 시도는 길이만 남는다
    assert w["stream_interruptions"] == [{"partial_chars": 120,
                                          "error": "스트림이 끊겼다: ReadError"}]
    assert [a["kind"] for a in w["llm_retries"]] == ["stream"]


async def test_stream_interrupted_twice_is_error_without_partial_body(fake_complete):
    fake_complete.side_effect = _complete_after(
        [_attempt(1, "stream", "스트림이 끊겼다: ReadError", 120),
         _attempt(2, "stream", "스트림이 finish_reason 없이 끝났다", 340)],
        StreamInterrupted("스트림이 finish_reason 없이 끝났다", 340))
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 1  # 다시 보내는 건 complete 의 몫이다
    assert w["is_error"] is True and w["error_code"] == "STREAM_INTERRUPTED"
    assert [i["partial_chars"] for i in w["stream_interruptions"]] == [120, 340]
    # 부분 응답을 열거나 저장하지 않는다
    assert w["json_status"] is None and w["final_text"] == "" and w["raw_text"] is None
    assert parse_wrapper(w).parse_status == "parse_failed"


async def test_stream_length_is_truncated_not_retried(fake_complete):
    fake_complete.side_effect = None
    fake_complete.return_value = ('{"ticker": "99', {**TRUNCATED_USAGE, "completion_tokens": 8000})
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert w["error_code"] == "OUTPUT_TRUNCATED" and fake_complete.await_count == 1


async def test_missing_usage_marks_cost_unavailable(fake_complete):
    fake_complete.side_effect = None
    fake_complete.return_value = (REPORT_TEXT, {"finish_reason": "stop", "cost_currency": "USD"})
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert not w["is_error"] and w["json_status"] == "clean"
    assert (w["cost"], w["cost_basis"], w["input_tokens"]) == (0.0, "unavailable", None)


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
    assert gen.check_input({**CAUSE, "target_date": "2026-9-18"}) == ["target_date 는 YYYY-MM-DD 여야 한다: '2026-9-18'"]
    assert [p.split(" ")[0] for p in gen.check_input({**CAUSE, "cutoff": "2026-09-18T15:30:00"})] == ["cutoff"]
    assert gen.check_input([]) == ["입력이 객체가 아니다: list"]
    broken = {k: v for k, v in CAUSE.items() if k != "code"} | {"change_pct": "-4.2"}
    assert gen.check_input(broken) == ["code 가 없다", "change_pct 는 숫자여야 한다: '-4.2'"]


def test_prompt_sha256_is_file_hash():
    import hashlib

    path = gen.PROMPT_DIR / "stock_analysis_system.md"
    assert gen.prompt_sha256() == hashlib.sha256(path.read_bytes()).hexdigest()


async def test_invalid_json_is_retried_once_and_recorded(fake_complete):
    broken = '{"ticker": "999990", "issue_ids": ["i13]}'
    fake_complete.side_effect = [(broken, USAGE), (REPORT_TEXT, USAGE)]
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 2
    assert w["json_status"] == "clean" and w["final_text"] == REPORT_TEXT
    assert w["json_retry"]["retried"] is True
    assert w["json_retry"]["first"]["json_status"] == "invalid"
    assert w["json_retry"]["first"]["raw_text"] == broken
    assert w["cost"] == pytest.approx(0.0123 * 2)  # 첫 시도 비용도 센다


async def test_invalid_twice_stays_invalid_after_one_retry(fake_complete):
    w = await run(fake_complete, "보고서를 쓰지 못했습니다.")
    assert fake_complete.await_count == 2
    assert w["json_status"] == "invalid" and w["json_retry"]["retried"] is True


@pytest.mark.parametrize("text, usage", [
    (REPORT_TEXT, USAGE),                                    # 열림
    ("", USAGE),                                             # 빈 응답
    ('{"ticker": "9', {**USAGE, "finish_reason": "length"}),  # 잘림
])
async def test_no_json_retry_for_clean_empty_or_truncated(fake_complete, text, usage):
    fake_complete.side_effect = None
    fake_complete.return_value = (text, usage)
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 1
    assert w["json_retry"] == {"retried": False}


async def test_llm_error_is_not_json_retried(fake_complete):
    w = await run(fake_complete, exc=LLMError("HTTP 500"))
    assert fake_complete.await_count == 1 and w["json_retry"] == {"retried": False}


FLAT = json.loads((FIXTURES / "sample_flat.json").read_text(encoding="utf-8"))


def _flat_report(with_move_link):
    """+0.45% 날 보고서. with_move_link 면 판단하지 않는 등락 층에 원인을 단다."""
    links = [{"layer": "move", "note": "n", "direction_match": True, "strength": "partial"}]
    return json.dumps({"ticker": "999980", "verdict": "partially_explained" if with_move_link else "no_clear_cause",
                       "relative_verdict": "no_clear_cause",
                       "factors": [{"event": "e", "links": links}] if with_move_link else []},
                      ensure_ascii=False)


async def test_judge_layer_violation_is_retried_once_with_same_input(fake_complete):
    bad, good = _flat_report(True), _flat_report(False)
    fake_complete.side_effect = [(bad, USAGE), (good, USAGE)]
    w = await gen.generate(FLAT, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 2
    # 피드백 문구 없이 같은 입력이다
    assert fake_complete.await_args_list[0].args == fake_complete.await_args_list[1].args
    assert json.loads(fake_complete.await_args.args[1])["market"]["judge_layers"] == {
        "move": False, "relative": False}
    assert w["final_text"] == good
    assert w["judge_retry"]["retried"] is True
    assert {p.split(":")[0] for p in w["judge_retry"]["first"]["problems"]} == {
        "FLAT_MOVE_VERDICT", "FLAT_MOVE_FACTORS"}
    assert w["judge_retry"]["first"]["final_text"] == bad
    assert w["cost"] == pytest.approx(0.0123 * 2)


async def test_judge_layer_violation_twice_is_left_for_verify(fake_complete):
    fake_complete.side_effect = None
    fake_complete.return_value = (_flat_report(True), USAGE)
    w = await gen.generate(FLAT, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 2
    assert w["judge_retry"]["retried"] is True and w["final_text"] == _flat_report(True)


async def test_no_judge_retry_when_layers_are_kept_or_report_unopened(fake_complete):
    fake_complete.side_effect = None
    fake_complete.return_value = (_flat_report(False), USAGE)
    w = await gen.generate(FLAT, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 1 and w["judge_retry"] == {"retried": False}
    assert w["judge_layers"] == {"move": False, "relative": False} and w["common_move"] is False


def _kb(change, peer, excess, messages=None):
    """직접 언급이 없는 KB금융 입력. 공통 시장 시황만 not_mentioned 로 들어온다(테마 동향 없음)."""
    return {"stock": "KB금융", "code": "105560", "target_date": "2026-10-23",
            "cutoff": "2026-10-23T15:30:00+09:00", "change_pct": change,
            "market": {"index": "코스피", "change_pct": 0.3, "as_of": "15:30", "url": "",
                       "peer_median_pct": peer, "peer_up": 4, "peer_down": 14, "peer_total": 19,
                       "excess_pct": excess},
            "messages": messages if messages is not None else [
                {"channel": "c", "url": "https://t.me/c/1", "datetime_kst": "2026-10-23T11:00:00+09:00",
                 "text": "코스피 마감 시황", "mention": "not_mentioned", "kind": "market_recap"}]}


async def test_no_direct_or_theme_message_gives_canned_report_without_llm(fake_complete):
    from app.services.stock_analysis.verify import verify

    payload = _kb(-3.1, -1.57, -1.53)
    w = await gen.generate(payload, system="SYS", prompt_hash="abc", run_id="r1")
    fake_complete.assert_not_called()
    assert w["skipped_llm"] == gen.NO_DIRECT_MESSAGES
    assert (w["json_status"], w["is_error"], w["cost"], w["schema_problems"]) == ("clean", False, 0.0, [])
    assert w["json_retry"] == w["judge_retry"] == {"retried": False}
    report = gen.report_of(w)
    assert verify(report, payload) == ("passed", [])
    assert (report["verdict"], report["relative_verdict"], report["factors"], report["events"]) == (
        "no_clear_cause", "no_clear_cause", [], [])
    assert (report["as_of"], report["display_as_of"], report["display_is_close"]) == (
        "2026-10-23T15:30:00+09:00", "2026-10-23T15:30:00+09:00", True)
    assert report["summary"]["move"] == (
        "오후 3시 30분 장 마감 기준 KB금융은 3.10% 내렸습니다. "
        "같은 시각 코스피는 0.30% 올랐고, 대형주 19개 중 14개가 내렸으며 중간값은 1.57% 하락이었습니다. "
        "KB금융은 대형주 전반보다 더 내렸습니다.")
    assert report["summary"]["main_cause"] == "제공된 메시지에서 확인된 원인은 없습니다."
    assert report["summary"]["unexplained"] == "이 종목을 직접 다룬 소식이 수집되지 않았습니다."


@pytest.mark.parametrize(("change", "peer", "excess", "relation", "common"), [
    (-1.68, -3.21, 1.53, "대형주 전반보다 덜 내렸습니다", False),
    (-0.5, -0.4, -0.1, "대형주 전반과 비슷하게 움직였습니다", True),   # 차이가 작고 대형주 몫이 절반 이상
    (0.5, -2.0, 2.5, "대형주 전반과 반대로 움직였습니다", False),
])
async def test_canned_move_relation_and_common_move(fake_complete, change, peer, excess, relation, common):
    report = gen.canned_report(_kb(change, peer, excess))
    assert report["summary"]["move"].endswith(f"KB금융은 {relation}.")
    assert report["summary"]["main_cause"].startswith("대형주 전반이 함께 내린 날이었습니다. ") is common


@pytest.mark.parametrize("extra", [
    {"mention": "mentioned", "kind": "news"},
    # 직접 언급이 없어도 테마 동향이 있으면 부른다. 업종 단락이 sector 근거가 될 수 있다
    {"mention": "not_mentioned", "kind": "theme_recap"},
])
async def test_direct_or_theme_recap_message_calls_llm(fake_complete, extra):
    payload = _kb(-3.1, -1.57, -1.53)
    payload["messages"].append({**payload["messages"][0], "url": "https://t.me/c/2", **extra})
    assert gen.needs_llm(payload)
    fake_complete.side_effect = None
    fake_complete.return_value = (REPORT_TEXT, USAGE)
    w = await gen.generate(payload, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 1 and "skipped_llm" not in w


BANKS = [{"code": "055550", "name": "신한지주"}, {"code": "086790", "name": "하나금융지주"},
         {"code": "316140", "name": "우리금융지주"}]


def _peer(relation, median=-3.04, group="은행지주", members=BANKS):
    return {"group": group, "median_change_rate_pct": median, "relation": relation, "members_used": members}


def _with_compare(kospi_relation, peers, *, change=-0.5, kospi=0.3, basis="kospi", ex_self=None, status="ok"):
    """_kb 입력에 market_compare 를 붙인다(러너가 MarketCompare.apply 로 넣는 칸)."""
    payload = _kb(change, -0.4, change + 0.4)
    payload["market"]["change_pct"] = kospi
    payload["market_compare"] = {"status": status, "status_reason": None, "peers": peers, "kospi": {
        "stock_change_rate_pct": change, "kospi_change_rate_pct": kospi, "kospi_basis": basis,
        "kospi_relation": kospi_relation, "kospi_weight_pct": 28.8, "kospi_contribution_pp": 0.513,
        "kospi_ex_self_change_rate_pct": ex_self}}
    return payload


WHO = "같은 은행지주 그룹의 신한지주·하나금융지주·우리금융지주"


@pytest.mark.parametrize(("payload", "kospi_sentence", "relative"), [
    (_with_compare("follows", [_peer("follows")], change=-2.5, kospi=-1.8),
     "KB금융은 코스피와 비슷하게 움직였습니다.",
     f"KB금융은 코스피, 그리고 대체로 3.04% 안팎 내린 {WHO}와 비슷하게 움직여 시장 전체 흐름을 따라갔습니다."),
    (_with_compare("diverges", [_peer("follows")], change=-2.5, kospi=1.2),
     "코스피는 올랐지만 KB금융은 내렸습니다.",
     f"코스피는 올랐지만 KB금융은 대체로 3.04% 안팎 내린 {WHO}와 함께 내렸습니다."),
    (_with_compare("diverges", [_peer("follows")], change=-2.5, kospi=-0.9),
     "KB금융은 코스피와 다르게 움직였습니다.",
     f"KB금융은 코스피와는 다르게 대체로 3.04% 안팎 내린 {WHO}와 함께 움직였습니다."),
    (_with_compare("opposite", [_peer("follows", -0.9)], change=-0.5, kospi=0.4),
     "코스피는 올랐고 KB금융은 내렸습니다.",
     f"코스피는 올랐고 KB금융은 대체로 0.90% 안팎 내린 {WHO}와 함께 내렸습니다."),
    (_with_compare("follows", [_peer("diverges")]),
     "KB금융은 코스피와 비슷하게 움직였습니다.",
     f"KB금융은 대체로 3.04% 안팎 내린 {WHO}와 크게 달랐습니다."),
    (_with_compare("follows", [_peer("opposite", 0.41)], change=-0.32),
     "KB금융은 코스피와 비슷하게 움직였습니다.",
     f"{WHO}는 대체로 0.41% 안팎 올랐고, KB금융은 0.32% 내렸습니다."),
    (_with_compare("follows", [_peer("inconclusive", -5.49, "메모리반도체", [{"code": "000660", "name": "SK하이닉스"}])]),
     "KB금융은 코스피와 비슷하게 움직였습니다.",
     "같은 메모리반도체 그룹의 SK하이닉스는 5.49% 내렸습니다."),
    # 비교 종목이 둘 이상인데 inconclusive 면 방향이 엇갈린 그룹이다. 그룹 등락률(대체로 X% 안팎)을 쓰지 않는다.
    # 코스피 판정이 follows 면 종목 자신의 결론(코스피를 따라갔다)을 앞에 남긴다
    (_with_compare("follows", [_peer("inconclusive", 0.0)]),
     "KB금융은 코스피와 비슷하게 움직였습니다.",
     f"KB금융은 코스피와 비슷하게 움직여 시장 전체 흐름을 따라갔습니다. {WHO}는 방향이 엇갈려 그룹 흐름과 비교하기 어렵습니다."),
    # 코스피 판정이 follows 가 아니면 엇갈림 문장만(코스피 비교는 summary.move 에 있다)
    (_with_compare("opposite", [_peer("inconclusive", 0.0)], change=-0.5, kospi=0.4),
     "코스피는 올랐고 KB금융은 내렸습니다.",
     f"{WHO}는 방향이 엇갈려 그룹 흐름과 비교하기 어렵습니다."),
    (_with_compare("diverges", [_peer("inconclusive", 1.11, "SK하이닉스 연동",
                                     [{"code": "000660", "name": "SK하이닉스"}, {"code": "034730", "name": "SK"}])],
                   change=-2.5, kospi=1.2),
     "코스피는 올랐지만 KB금융은 내렸습니다.",
     "SK하이닉스 지분으로 이어진 SK하이닉스·SK는 방향이 엇갈려 그룹 흐름과 비교하기 어렵습니다."),
    # 연동 그룹은 지분으로 이어진 관계로 쓴다
    (_with_compare("follows", [_peer("follows", 1.2, "SK하이닉스 연동",
                                     [{"code": "000660", "name": "SK하이닉스"}, {"code": "034730", "name": "SK"}])],
                   change=1.0, kospi=0.8),
     "KB금융은 코스피와 비슷하게 움직였습니다.",
     ("KB금융은 코스피, 그리고 대체로 1.20% 안팎 오른 SK하이닉스 지분으로 이어진 SK하이닉스·SK와 비슷하게 움직여 "
      "시장 전체 흐름을 따라갔습니다.")),
    # 그룹이 없는 종목도 코스피 비교는 move 에 나온다
    (_with_compare("follows", []), "KB금융은 코스피와 비슷하게 움직였습니다.", None),
    # 그룹 판정이 null 이면 그룹 문장이 없다
    (_with_compare("diverges", [_peer(None)], change=-2.5, kospi=1.2), "코스피는 올랐지만 KB금융은 내렸습니다.", None),
])
def test_canned_report_writes_compare_sentences_that_pass_verify(payload, kospi_sentence, relative):
    from app.services.stock_analysis.verify import (
        COMPARE_META_PHRASE,
        COMPARE_OPPOSITE_WORDING,
        check_warnings,
        code_of,
        verify,
    )

    report = gen.canned_report(payload)
    assert report["summary"]["move"].endswith(" " + kospi_sentence)
    assert report["summary"]["relative"] == relative
    assert verify(report, payload) == ("passed", [])
    warned = {code_of(w) for w in check_warnings(report, payload)}
    assert not warned & {COMPARE_META_PHRASE, COMPARE_OPPOSITE_WORDING}


def test_canned_kospi_ex_self_writes_weight_share_and_ex_self():
    """비중이 큰 종목은 프롬프트 4부 move 처럼 비중·기여도·자기 제외 코스피와 판정을 쓴다."""
    payload = _with_compare("diverges", [_peer("follows", 5.81, "메모리반도체", [{"code": "000660", "name": "SK하이닉스"}])],
                            change=4.9, kospi=3.0, basis="kospi_ex_self", ex_self=2.4)
    payload["stock"] = "삼성전자"
    report = gen.canned_report(payload)
    assert report["summary"]["move"].endswith(
        " 삼성전자는 코스피 비중이 28.80%여서 코스피 등락 가운데 0.513%포인트를 끌어올렸고,"
        " 삼성전자를 뺀 코스피는 2.40% 올라 삼성전자는 시장 흐름과 다르게 움직였습니다.")
    assert report["summary"]["relative"] == (
        "삼성전자는 삼성전자를 뺀 코스피와는 다르게 5.81% 오른 같은 메모리반도체 그룹의 SK하이닉스와 함께 움직였습니다.")


EX_SELF_HEAD = "삼성전자는 코스피 비중이 28.80%여서 코스피 등락 가운데 "


@pytest.mark.parametrize(("relation", "change", "kospi", "ex_self", "share", "sentence"), [
    ("follows", 2.9, 3.0, 2.4, 0.513,
     "0.513%포인트를 끌어올렸고, 삼성전자를 뺀 코스피는 2.40% 올라 삼성전자는 시장 흐름과 비슷하게 움직였습니다."),
    # diverges 인데 방향이 반대면 각자의 방향을 쓰고 판정을 붙인다(프롬프트 3단계 kospi_relation 표)
    ("diverges", 1.2, 0.1, -0.2, 0.346,
     "0.346%포인트를 끌어올렸고, 삼성전자를 뺀 코스피는 0.20% 내렸지만 삼성전자는 올라 시장 흐름과 다르게 움직였습니다."),
    # opposite 는 판정하는 말 없이 방향만
    ("opposite", 0.3, -0.06, -0.2, 0.086, "0.086%포인트를 끌어올렸고, 삼성전자를 뺀 코스피는 0.20% 내렸고 삼성전자는 올랐습니다."),
    # 이 종목이 코스피를 끌어내린 날
    ("follows", -2.0, -2.0, -1.5, -0.576,
     "0.576%포인트를 끌어내렸고, 삼성전자를 뺀 코스피는 1.50% 내려 삼성전자는 시장 흐름과 비슷하게 움직였습니다."),
])
def test_canned_kospi_ex_self_is_one_sentence_and_move_stays_within_four(relation, change, kospi, ex_self, share,
                                                                          sentence):
    """비중·기여도와 자기 제외 코스피 판정을 한 문장으로 합친다. move 는 프롬프트 4부 상한(최대 4문장) 안이다."""
    from app.services.stock_analysis.verify import (
        COMPARE_OPPOSITE_WORDING,
        check_warnings,
        code_of,
        verify,
    )

    payload = _with_compare(relation, [_peer("follows")], change=change, kospi=kospi, basis="kospi_ex_self",
                            ex_self=ex_self)
    payload["stock"] = "삼성전자"
    payload["market_compare"]["kospi"]["kospi_contribution_pp"] = share
    report = gen.canned_report(payload)
    move = report["summary"]["move"]
    assert move.endswith(" " + EX_SELF_HEAD + sentence)
    # 머리 + 같은 시각 코스피·대형주 + 대형주 비교 + 코스피 판정
    assert len(re.findall(r"다\.(?:\s|$)", move)) == 4
    assert verify(report, payload) == ("passed", [])
    assert COMPARE_OPPOSITE_WORDING not in {code_of(w) for w in check_warnings(report, payload)}


def test_canned_two_groups_mention_kospi_once():
    """그룹마다 한 문장. 코스피는 첫 follows 그룹 문장에만 쓴다."""
    payload = _with_compare("diverges", [_peer("follows"), _peer("follows", 1.2, "보험", [{"code": "000810", "name": "삼성화재"}])],
                            change=-2.5, kospi=1.2)
    assert gen.canned_report(payload)["summary"]["relative"] == (
        f"코스피는 올랐지만 KB금융은 대체로 3.04% 안팎 내린 {WHO}와 함께 내렸습니다. "
        "KB금융은 1.20% 오른 같은 보험 그룹의 삼성화재와 함께 내렸습니다.")


@pytest.mark.parametrize("status", ["no_data", "no_trades", "stock_not_found"])
def test_canned_report_has_no_compare_sentence_unless_ok(status):
    payload = _with_compare("follows", [_peer("follows")], status=status)
    report = gen.canned_report(payload)
    assert report["summary"]["relative"] is None
    assert "코스피와" not in report["summary"]["move"]
    payload.pop("market_compare")
    assert gen.canned_report(payload)["summary"]["relative"] is None


@pytest.mark.parametrize(("target_date", "cutoff", "shown", "phrase"), [
    # 전날 종가를 다음 날 아침에 돌린 입력. 보고서는 전날 장 마감 기준이다
    ("2026-11-02", "2026-11-03T08:30:00+09:00", "15:30", "오후 3시 30분 장 마감 기준"),
    ("2026-11-02", "2026-11-02T15:30:00+09:00", "15:30", "오후 3시 30분 장 마감 기준"),
    # 장 마감이 16:30 으로 늦춰지는 날(수능). 16:30 이 장 마감이고 15:30 은 아직 장중이다
    ("2026-11-19", "2026-11-19T16:30:00+09:00", "16:30", "오후 4시 30분 장 마감 기준"),
    ("2026-11-19", "2026-11-19T15:30:00+09:00", "15:30", "오후 3시 30분 기준"),
    ("2026-11-02", "2026-11-02T11:00:00+09:00", "11:00", "오전 11시 기준"),
])
def test_display_as_of_is_market_close_after_close_and_cutoff_before(target_date, cutoff, shown, phrase):
    payload = {**_kb(-3.1, -1.57, -1.53), "target_date": target_date, "cutoff": cutoff}
    report = gen.canned_report(payload)
    assert report["as_of"] == cutoff  # 데이터 시각은 메시지를 자른 시각 그대로
    assert report["display_as_of"] == f"{target_date}T{shown}:00+09:00"
    assert report["display_is_close"] is ("장 마감" in phrase)
    assert report["summary"]["move"].startswith(f"{phrase} KB금융은 3.10% 내렸습니다.")
    sent = gen.model_input(payload)
    assert (sent["display_as_of"], sent["as_of_phrase"]) == (shown, phrase)
    assert sent["cutoff"] == cutoff  # 메시지를 자른 시각은 그대로 보낸다
    assert "as_of" not in sent


def test_canned_report_without_market_or_messages():
    payload = {**_kb(0, None, None, messages=[]), "market": None, "cutoff": "2026-10-23T11:00:00+09:00"}
    report = gen.canned_report(payload)
    assert report["summary"]["move"] == "오전 11시 기준 KB금융은 등락이 없었습니다."
    assert (report["as_of"], report["display_as_of"], report["display_is_close"]) == (
        "2026-10-23T11:00:00+09:00", "2026-10-23T11:00:00+09:00", False)


def _msg(n, kind, mention="not_mentioned", **kw):
    return {"channel": "c", "url": f"https://t.me/c/{n}", "datetime_kst": "2026-10-23T11:00:00+09:00",
            "text": "t", "mention": mention, "kind": kind, "after_prev_close": False, "first_seen_kst": None, **kw}


def test_model_input_splits_messages_into_three_columns():
    msgs = [_msg(1, "news", "mentioned"), _msg(2, "market_recap", "mentioned"), _msg(3, "flow_rank", "mentioned"),
            _msg(4, "theme_recap"), _msg(5, "theme_recap", after_prev_close=True), _msg(6, "disclosure"),
            {**_msg(7, None), "kind": None}]
    payload = {**_kb(-3.1, -1.57, -1.53, messages=msgs), "market": {**_kb(-3.1, -1.57, -1.53)["market"],
                                                                    "move_case": "normal"}}
    sent = gen.model_input(payload)
    urls = {k: [m["url"][-1] for m in sent[k]] for k in ("messages", "market_context", "flow")}
    assert [m["id"] for m in sent["messages"]] == ["m1", "m2", "m3", "m4"]  # 근거 칸에만, 칸 안 순서대로
    assert all("id" not in m for m in sent["market_context"] + sent["flow"])
    # 전날 장 설명(after_prev_close)은 kind 와 상관없이 market_context. kind 가 없으면 messages
    assert urls == {"messages": ["1", "4", "6", "7"], "market_context": ["2", "5"], "flow": ["3"]}
    assert "move_case" not in sent["market"] and sent["market"]["judge_layers"] == {"move": True, "relative": True}
    assert len(payload["messages"]) == 7  # 원본은 그대로


def _legacy_msg(n, kind, match):
    """mention 이름을 바꾸기 전 입력 메시지. match: direct|indirect."""
    m = _msg(n, kind)
    del m["mention"]
    return {**m, "match": match}


def test_model_input_moves_legacy_match_to_mention():
    """옛 입력의 match 는 세 칸 모두 mention 으로 옮겨 보낸다 — 프롬프트는 mention 만 설명한다."""
    payload = _kb(-3.1, -1.57, -1.53, messages=[
        _legacy_msg(1, "news", "direct"), _legacy_msg(2, "market_recap", "indirect"),
        _legacy_msg(3, "flow_rank", "indirect")])
    sent = gen.model_input(payload)
    got = [(m["url"][-1], m["mention"]) for k in ("messages", "market_context", "flow") for m in sent[k]]
    assert got == [("1", "mentioned"), ("2", "not_mentioned"), ("3", "not_mentioned")]
    assert not any("match" in m for k in ("messages", "market_context", "flow") for m in sent[k])
    assert "match" in payload["messages"][0]  # 원본은 그대로
    assert gen.needs_llm(payload) and gen.direct_message_count(payload) == 1
    assert not gen.needs_llm(_kb(-3.1, -1.57, -1.53, messages=[_legacy_msg(1, "news", "indirect")]))


@pytest.mark.parametrize(("msgs", "llm"), [
    ([_msg(1, "market_recap", "mentioned")], False),                  # 시황은 mentioned 여도 근거 칸이 아니다
    ([_msg(1, "flow_rank", "mentioned")], False),
    ([_msg(1, "theme_recap", after_prev_close=True)], False),       # 전날 장 설명인 테마 동향은 참고만
    ([_msg(1, "theme_recap")], True),
    ([_msg(1, "news", "mentioned")], True),
])
def test_needs_llm_counts_only_messages_column(msgs, llm):
    assert gen.needs_llm(_kb(-3.1, -1.57, -1.53, messages=msgs)) is llm


async def test_timeout_retry_by_client_is_recorded(fake_complete):
    fake_complete.side_effect = _complete_after(
        [_attempt(1, "timeout", "LLM 호출 실패: TimeoutError (420초 제한)", elapsed=420.0)],
        (REPORT_TEXT, USAGE))
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 1 and not w["is_error"]
    assert w["timeouts"] == [{"error": "LLM 호출 실패: TimeoutError (420초 제한)", "seconds": 420.0}]


async def test_timeout_after_client_retries_is_llm_error(fake_complete):
    error = "LLM 호출 실패: TimeoutError (420초 제한)"
    fake_complete.side_effect = _complete_after(
        [_attempt(n, "timeout", error) for n in (1, 2, 3)], LLMTimeout(error))
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 1
    assert w["is_error"] and w["error_code"] == "LLM_ERROR" and len(w["timeouts"]) == 3


async def test_http_429_after_client_retries_is_llm_error(fake_complete):
    fake_complete.side_effect = _complete_after(
        [_attempt(n, "http_429", "LLM 호출 실패: HTTP 429 rate limited") for n in (1, 2, 3)],
        LLMError("LLM 호출 실패: HTTP 429 rate limited"))
    w = await gen.generate(CAUSE, system="SYS", prompt_hash="abc", run_id="r1")
    assert w["is_error"] and w["error_code"] == "LLM_ERROR"
    assert [a["kind"] for a in w["llm_retries"]] == ["http_429"] * 3 and w["timeouts"] == []



async def test_move_strength_cap_violation_is_retried(fake_complete):
    """대형주 몫이 절반 이상인 날 등락 층 종목 고유 재료를 sufficient 로 달면 같은 입력으로 한 번 더 부른다."""
    share = json.loads((FIXTURES / "sample_market_share_down.json").read_text(encoding="utf-8"))
    msg = share["messages"][0]
    assert msg["mention"] == "mentioned"
    def report(strength):
        return json.dumps({"ticker": share["code"], "verdict": "explained" if strength == "sufficient" else "partially_explained",
                           "relative_verdict": "no_clear_cause",
                           "factors": [{"event": "e", "stance": "bearish", "links": [
                               {"layer": "move", "note": "n", "direction_match": True, "strength": strength}],
                               "sources": [{"url": msg["url"], "mention": "mentioned"}]}]}, ensure_ascii=False)
    fake_complete.side_effect = [(report("sufficient"), USAGE), (report("partial"), USAGE)]
    w = await gen.generate(share, system="SYS", prompt_hash="abc", run_id="r1")
    assert fake_complete.await_count == 2 and w["judge_retry"]["retried"] is True
    assert [p.split(":")[0] for p in w["judge_retry"]["first"]["problems"]] == ["MOVE_SUFFICIENT_STOCK_ONLY"]
    assert json.loads(fake_complete.await_args.args[1])["market"]["move_strength_cap"] == "partial"



def test_model_input_has_sector_and_universe_weight_from_stock_table():
    payload = {**CAUSE, "code": "402340", "stock": "SK스퀘어"}
    sent = gen.model_input(payload)
    assert sent["sector"] == ["지주", "반도체"]
    assert sent["market"]["universe_weight"] == pytest.approx(0.0326)
