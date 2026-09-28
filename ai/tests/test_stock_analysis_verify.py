"""⑤ 근거 검증. 순수 함수라 LLM·DB 없이 돈다.

입력은 샘플 픽스처(`fixtures/stock_analysis/`)를 쓰고, 보고서는 여기서 규칙을 지키는
한 편을 만든 뒤 칸을 하나씩 망가뜨려 해당 코드가 나오는지 본다.
"""

import copy
import json
from pathlib import Path

import pytest

from app.services.stock_analysis.verify import (
    ASKED_QUESTION,
    CHANGE_PCT_MISMATCH,
    DATE_MISMATCH,
    DIRECTION_MISMATCH,
    EMPTY_RESPONSE,
    FACTOR_WITHOUT_SOURCE,
    FLAT_MOVE_FACTORS,
    FLAT_MOVE_VERDICT,
    JSON_INVALID,
    LLM_ERROR,
    QUOTE_NOT_IN_SOURCE,
    SCHEMA_MISSING,
    SCHEMA_TYPE,
    SCHEMA_VALUE,
    SIZE_FIT_OVER_CAP,
    TICKER_MISMATCH,
    UNCONFIRMED_OVER_CAP,
    URL_IS_LINK_BODY,
    URL_NOT_IN_INPUT,
    VERDICT_SIZE_FIT,
    check_grounding,
    check_rules,
    check_schema,
    code_of,
    is_flat_move,
    verify,
    verify_wrapper,
)

FIXTURES = Path(__file__).parent / "fixtures" / "stock_analysis"
CAUSE = json.loads((FIXTURES / "sample_cause.json").read_text(encoding="utf-8"))
FLAT = json.loads((FIXTURES / "sample_flat.json").read_text(encoding="utf-8"))

DIRECT_URL = "https://t.me/sample_channel_a/101"
INDIRECT_URL = "https://t.me/sample_channel_b/202"
# 메시지 text 에서 글자 그대로 뜬 것
DIRECT_QUOTE = "3분기 영업이익 잠정치 412억원… 시장 예상치 590억원"
# 같은 메시지에 딸린 기사 excerpt 에서 뜬 것
EXCERPT_QUOTE = "주요 고객사의 재고 조정으로 출하량이 줄었다고"
INDIRECT_QUOTE = "전방 스마트폰 수요 둔화 우려로"


def source(url=DIRECT_URL, quote=DIRECT_QUOTE, match="direct"):
    return {"channel": "sample_channel_a", "url": url, "datetime_kst": "2026-09-18T08:10:00+09:00",
            "quote": quote, "match": match, "is_market_recap": False}


def factor(size_fit="sufficient", sources=None, **kw):
    f = {"claim": "실적이 예상보다 나빴습니다.", "detail": "부연.",
         "stance": "bearish", "direction_match": True, "size_fit": size_fit,
         "unconfirmed": False, "sources": sources if sources is not None else [source()]}
    f.update(kw)
    return f


def cause_report(**kw):
    r = {
        "ticker": "999990", "name": "솔마루전자", "date": "2026-09-18", "as_of": "15:30",
        "change_pct": -4.2, "verdict": "explained",
        "summary": {"move": "m", "main_cause": "c", "counter": None, "unexplained": "u"},
        "factors": [factor()],
        "terms": [{"plain": "미리 발표한 실적", "term": "잠정실적"}],
        "background": {"bullish": [], "bearish": [],
                       "neutral": ["n", {"text": "다음 일정", "watch": True}]},
        "not_found": [],
    }
    r.update(kw)
    return r


def flat_report(**kw):
    return cause_report(**{"ticker": "999980", "name": "하늬결화학", "as_of": "11:00",
                           "change_pct": 0.45, "verdict": "no_clear_cause", "factors": [], **kw})


def codes(problems):
    return {code_of(p) for p in problems}


def test_valid_reports_pass():
    assert verify(cause_report(), CAUSE) == ("passed", [])
    assert verify(flat_report(), FLAT) == ("passed", [])


# --- 스키마 ---------------------------------------------------------------


def test_schema_missing_top_level_and_summary_fields():
    r = cause_report()
    del r["not_found"]
    del r["summary"]["unexplained"]
    problems = check_schema(r)
    assert f"{SCHEMA_MISSING}: not_found" in problems
    assert f"{SCHEMA_MISSING}: summary.unexplained" in problems


def test_schema_values_outside_prompt_lists():
    r = cause_report(verdict="mostly_explained",
                     factors=[factor(size_fit="medium", stance="up",
                                     sources=[source(match="related")])])
    problems = check_schema(r)
    assert all(code_of(p) == SCHEMA_VALUE for p in problems)
    assert {p.split(":", 1)[1].split("=")[0].strip() for p in problems} == {
        "verdict", "factors[0].size_fit", "factors[0].stance", "factors[0].sources[0].match"}


def test_schema_bool_fields_reject_strings():
    """"false" 문자열을 참으로 받으면 뜻이 뒤집힌다(적재 모듈 _as_bool 과 같은 이유)."""
    r = cause_report(factors=[factor(direction_match="true", unconfirmed="false")])
    assert codes(check_schema(r)) == {SCHEMA_TYPE}


def test_schema_counter_null_is_ok_but_others_cannot_be_empty():
    assert check_schema(cause_report()) == []
    r = cause_report(summary={"move": "", "main_cause": "c", "counter": None, "unexplained": "u"})
    assert check_schema(r) == [f"{SCHEMA_VALUE}: summary.move 는 비울 수 없다"]


def test_schema_background_needs_all_three_slots():
    r = cause_report(background={"bullish": [], "bearish": []})
    assert check_schema(r) == [f"{SCHEMA_MISSING}: background.neutral"]


def test_schema_change_pct_must_be_number_not_bool():
    assert codes(check_schema(cause_report(change_pct=True))) == {SCHEMA_TYPE}
    assert codes(check_schema(cause_report(change_pct="-4.2"))) == {SCHEMA_TYPE}


# --- 규칙: ±1% ------------------------------------------------------------


@pytest.mark.parametrize(("pct", "flat"), [
    (0.99, True), (1.00, True), (1.01, False),
    (-0.99, True), (-1.00, True), (-1.01, False),
])
def test_flat_move_boundary_is_inclusive(pct, flat):
    assert is_flat_move(pct) is flat


@pytest.mark.parametrize(("pct", "flagged"), [(0.99, True), (1.00, True), (1.01, False)])
def test_flat_move_rule_at_boundary(pct, flagged):
    """입력이 경계 안이면 원인을 대면 안 된다. 1.01 이면 explained 가 정상일 수 있다."""
    payload = {**CAUSE, "change_pct": pct}
    r = cause_report(change_pct=pct, factors=[factor()])
    flat_codes = codes(check_rules(r, payload)) & {FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS}
    assert flat_codes == ({FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS} if flagged else set())


def test_flat_move_uses_input_change_pct_not_report():
    """보고서가 등락률을 잘못 옮겨 적었다고 규칙을 피해 가면 안 된다."""
    r = cause_report(ticker="999980", date="2026-09-18", change_pct=-4.2)
    got = codes(check_rules(r, FLAT))
    assert {FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS, CHANGE_PCT_MISMATCH} <= got


def test_flat_move_with_empty_factors_but_wrong_verdict():
    r = flat_report(verdict="partially_explained")
    got = codes(check_rules(r, FLAT))
    assert FLAT_MOVE_VERDICT in got
    assert FLAT_MOVE_FACTORS not in got


# --- 규칙: 상한·방향 ------------------------------------------------------


def test_indirect_only_factor_cannot_be_sufficient():
    r = cause_report(verdict="explained", factors=[
        factor("sufficient", [source(INDIRECT_URL, INDIRECT_QUOTE, "indirect")])])
    assert SIZE_FIT_OVER_CAP in codes(check_rules(r, CAUSE))


def test_indirect_partial_and_mixed_sources_are_fine():
    partial = cause_report(verdict="partially_explained", factors=[
        factor("partial", [source(INDIRECT_URL, INDIRECT_QUOTE, "indirect")])])
    mixed = cause_report(factors=[factor("sufficient", [
        source(), source(INDIRECT_URL, INDIRECT_QUOTE, "indirect")])])
    assert verify(partial, CAUSE) == ("passed", [])
    assert verify(mixed, CAUSE) == ("passed", [])


def test_unconfirmed_factor_cannot_be_sufficient():
    r = cause_report(factors=[factor("sufficient", unconfirmed=True)])
    assert UNCONFIRMED_OVER_CAP in codes(check_rules(r, CAUSE))


def test_direction_match_false_does_not_belong_in_factors():
    r = cause_report(factors=[factor(direction_match=False)])
    assert DIRECTION_MISMATCH in codes(check_rules(r, CAUSE))


# --- 규칙: 판정표 ---------------------------------------------------------


@pytest.mark.parametrize(("verdict", "fits", "ok"), [
    ("explained", ["sufficient"], True),
    ("explained", ["partial", "sufficient"], True),
    ("explained", ["partial"], False),
    ("partially_explained", ["partial", "insufficient"], True),
    ("partially_explained", ["partial", "sufficient"], False),
    ("partially_explained", [], False),
    ("no_clear_cause", [], True),
    ("no_clear_cause", ["insufficient"], False),
])
def test_verdict_table(verdict, fits, ok):
    r = cause_report(verdict=verdict, factors=[factor(fit) for fit in fits])
    assert (VERDICT_SIZE_FIT not in codes(check_rules(r, CAUSE))) is ok


def _without_size_fit():
    f = factor()
    del f["size_fit"]
    return f


@pytest.mark.parametrize(("case", "report", "schema_code"), [
    ("size_fit 누락", cause_report(factors=[_without_size_fit()]), SCHEMA_MISSING),
    ("size_fit 목록 밖", cause_report(factors=[factor("medium")]), SCHEMA_VALUE),
    ("size_fit null", cause_report(factors=[factor(None)]), SCHEMA_VALUE),
    ("verdict 목록 밖", cause_report(verdict="mostly_explained"), SCHEMA_VALUE),
    ("factors 가 배열 아님", cause_report(factors={"claim": "c"}), SCHEMA_TYPE),
    ("factor 가 객체 아님", cause_report(factors=["원인 한 줄"]), SCHEMA_TYPE),
])
def test_verdict_table_is_skipped_when_its_inputs_break_schema(case, report, schema_code):
    """판정 재료가 스키마를 어기면 스키마 실패로만 센다. 같은 원인을 두 번 세지 않는다."""
    status, problems = verify(report, CAUSE)
    assert status == "failed", case
    assert schema_code in codes(problems), case
    assert VERDICT_SIZE_FIT not in codes(problems), case


# --- 규칙: 입력과 대조 ----------------------------------------------------


@pytest.mark.parametrize(("got", "ok"), [(-4.2, True), (-4.21, True), (-4.19, True),
                                         (-4.22, False), (-4.18, False)])
def test_change_pct_tolerance_is_0_01(got, ok):
    """float 로 빼면 4.21 - 4.2 가 0.01 을 살짝 넘는다. 경계가 흔들리면 안 된다."""
    assert (CHANGE_PCT_MISMATCH not in codes(check_rules(cause_report(change_pct=got), CAUSE))) is ok


def test_ticker_and_date_must_match_input():
    r = cause_report(ticker="999999", date="2026-09-17")
    assert {TICKER_MISMATCH, DATE_MISMATCH} <= codes(check_rules(r, CAUSE))


# --- 근거 -----------------------------------------------------------------


def test_quotes_from_text_and_excerpt_pass():
    r = cause_report(factors=[factor(sources=[source(), source(quote=EXCERPT_QUOTE)])])
    assert check_grounding(r, CAUSE) == []


def test_quote_whitespace_is_normalized():
    r = cause_report(factors=[factor(sources=[source(quote="3분기  영업이익\n잠정치 412억원…")])])
    assert check_grounding(r, CAUSE) == []


@pytest.mark.parametrize("changed", [
    "3분기 영업이익 잠정치 413억원… 시장 예상치 590억원",  # 숫자 한 글자
    "3분기 영업이익 잠정치 412억원... 시장 예상치 590억원",  # 말줄임표를 마침표 셋으로
    "3분기 영업 이익 잠정치 412억원",  # 공백을 더한 것도 글자가 달라진 것이다
])
def test_quote_with_one_char_changed_fails(changed):
    r = cause_report(factors=[factor(sources=[source(quote=changed)])])
    assert codes(check_grounding(r, CAUSE)) == {QUOTE_NOT_IN_SOURCE}


def test_quote_from_other_message_fails():
    """다른 메시지 문장을 이 출처에 붙이면 떨어진다. 입력 전체가 아니라 그 메시지에서 찾는다."""
    r = cause_report(factors=[factor(sources=[source(DIRECT_URL, INDIRECT_QUOTE)])])
    assert codes(check_grounding(r, CAUSE)) == {QUOTE_NOT_IN_SOURCE}


def test_empty_quote_fails():
    r = cause_report(factors=[factor(sources=[source(quote="  ")])])
    assert codes(check_grounding(r, CAUSE)) == {QUOTE_NOT_IN_SOURCE}


def test_link_body_url_as_source_has_its_own_code():
    """기사 주소를 쓴 건 지어낸 주소와 구분해 센다. quote 는 그 링크가 딸린 메시지에서 찾는다."""
    for url in ("https://example.com/s/a1b2c3", "https://news.example.com/article/1001"):
        r = cause_report(factors=[factor(sources=[source(url, EXCERPT_QUOTE)])])
        assert codes(check_grounding(r, CAUSE)) == {URL_IS_LINK_BODY}


def test_made_up_url_fails():
    r = cause_report(factors=[factor(sources=[source("https://t.me/sample_channel_a/999")])])
    assert codes(check_grounding(r, CAUSE)) == {URL_NOT_IN_INPUT}


def test_factor_without_source_fails():
    r = cause_report(factors=[factor(sources=[])])
    assert codes(check_grounding(r, CAUSE)) == {FACTOR_WITHOUT_SOURCE}


def test_verify_does_not_mutate_inputs():
    r, payload = cause_report(), copy.deepcopy(CAUSE)
    before = copy.deepcopy(r)
    verify(r, payload)
    assert r == before and payload == CAUSE


# --- 래퍼 단위 판정 -------------------------------------------------------


def test_verify_wrapper_codes_for_unreadable_reports():
    assert verify_wrapper({"is_error": True, "error_code": LLM_ERROR, "error": "HTTP 429"},
                          None, CAUSE) == ("failed", [f"{LLM_ERROR}: HTTP 429"])
    status, problems = verify_wrapper(
        {"is_error": True, "error_code": EMPTY_RESPONSE, "error": "빈 응답"}, None, CAUSE)
    assert status == "failed" and codes(problems) == {EMPTY_RESPONSE}
    status, problems = verify_wrapper(
        {"is_error": False, "json_status": "invalid", "asked_question": True}, None, CAUSE)
    assert status == "failed" and codes(problems) == {JSON_INVALID, ASKED_QUESTION}
    assert verify_wrapper({"is_error": False, "json_status": "clean"}, cause_report(),
                          CAUSE) == ("passed", [])
