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
    BACKGROUND_WITHOUT_SOURCE,
    CHANGE_PCT_MISMATCH,
    COUNTER_WITHOUT_BACKGROUND,
    DATE_MISMATCH,
    DIRECTION_MATCH_WRONG,
    DIRECTION_MISMATCH,
    EMPTY_RESPONSE,
    EVENT_REASON_MISMATCH,
    FACTOR_WITHOUT_SOURCE,
    FLAT_MOVE,
    FLAT_MOVE_FACTORS,
    FLAT_MOVE_VERDICT,
    FLAT_RELATIVE,
    FLAT_RELATIVE_FACTORS,
    FLAT_RELATIVE_VERDICT,
    JSON_INVALID,
    LLM_ERROR,
    MOVE_SUFFICIENT_STOCK_ONLY,
    OUTPUT_TRUNCATED,
    QUOTE_NOT_IN_SOURCE,
    RELATIVE_VERDICT_SIZE_FIT,
    SCHEMA_MISSING,
    SCHEMA_TYPE,
    SCHEMA_VALUE,
    SIZE_FIT_OVER_CAP,
    SOURCES_OVER_MAX,
    TICKER_MISMATCH,
    UNCONFIRMED_OVER_CAP,
    URL_IS_LINK_BODY,
    URL_NOT_IN_INPUT,
    VERDICT_SIZE_FIT,
    check_events,
    check_grounding,
    check_rules,
    check_schema,
    code_of,
    families_of,
    is_stock_specific,
    layer_pct,
    move_case,
    verify,
    verify_wrapper,
)

FIXTURES = Path(__file__).parent / "fixtures" / "stock_analysis"
CAUSE = json.loads((FIXTURES / "sample_cause.json").read_text(encoding="utf-8"))
FLAT = json.loads((FIXTURES / "sample_flat.json").read_text(encoding="utf-8"))
MARKET = json.loads((FIXTURES / "sample_market_driven.json").read_text(encoding="utf-8"))
LESS_DOWN = json.loads((FIXTURES / "sample_less_down.json").read_text(encoding="utf-8"))
UP_NO_CAUSE = json.loads((FIXTURES / "sample_up_no_cause.json").read_text(encoding="utf-8"))
TWO_LAYERS = json.loads((FIXTURES / "sample_two_layers.json").read_text(encoding="utf-8"))
MORE_DOWN = json.loads((FIXTURES / "sample_more_down.json").read_text(encoding="utf-8"))
BIG_UP = json.loads((FIXTURES / "sample_big_up.json").read_text(encoding="utf-8"))
MARKET_SHARE = json.loads((FIXTURES / "sample_market_share_down.json").read_text(encoding="utf-8"))

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
    f = {"claim": "실적이 예상보다 나빴습니다.", "detail": "부연.", "layer": "move",
         "stance": "bearish", "direction_match": True, "size_fit": size_fit,
         "unconfirmed": False, "sources": sources if sources is not None else [source()]}
    f.update(kw)
    return f


def bg(text="n", sources=None, **kw):
    """background 항목. 출처 기본값은 CAUSE 의 간접 메시지다."""
    item = {"text": text,
            "sources": sources if sources is not None
            else [source(INDIRECT_URL, INDIRECT_QUOTE, "indirect")]}
    item.update(kw)
    return item


def msg_source(payload, k=0, length=15):
    """payload 의 k 번째 메시지 text 앞부분을 그대로 뜬 출처."""
    m = payload["messages"][k]
    return source(m["url"], m["text"][:length], m["match"])


def cause_report(**kw):
    r = {
        "ticker": "999990", "name": "솔마루전자", "date": "2026-09-18", "as_of": "15:30",
        "change_pct": -4.2, "verdict": "explained", "relative_verdict": "no_clear_cause",
        "summary": {"move": "m", "main_cause": "c", "relative": None, "counter": None,
                    "unexplained": "u"},
        "factors": [factor()],
        "terms": [{"plain": "미리 발표한 실적", "term": "잠정실적"}],
        "background": {"bullish": [], "bearish": [],
                       "neutral": [bg(), bg("다음 일정", [source(quote=EXCERPT_QUOTE)], watch=True)]},
        "not_found": [],
    }
    r.update(kw)
    return r


def flat_report(**kw):
    background = {"bullish": [bg("착공 예정", [msg_source(FLAT, 0)], watch=True)],
                  "bearish": [bg("업황 부담", [msg_source(FLAT, 1)])], "neutral": []}
    return cause_report(**{"ticker": "999980", "name": "하늬결화학", "as_of": "11:00",
                           "change_pct": 0.45, "verdict": "no_clear_cause", "factors": [],
                           "background": background, **kw})


def rel(size_fit="sufficient", sources=None, **kw):
    """상대 층 factor."""
    return factor(size_fit, sources, **{"layer": "relative", **kw})


def summary(**kw):
    return {"move": "m", "main_cause": "c", "relative": None, "counter": None,
            "unexplained": "u", **kw}


def codes(problems):
    return {code_of(p) for p in problems}


def test_valid_reports_pass():
    assert verify(cause_report(), CAUSE) == ("passed", [])
    assert verify(flat_report(), FLAT) == ("passed", [])


# --- 스키마 ---------------------------------------------------------------


def test_schema_missing_top_level_and_summary_fields():
    r = cause_report()
    del r["not_found"]
    del r["relative_verdict"]
    del r["summary"]["unexplained"]
    del r["summary"]["relative"]
    del r["factors"][0]["layer"]
    problems = check_schema(r)
    assert f"{SCHEMA_MISSING}: not_found" in problems
    assert f"{SCHEMA_MISSING}: relative_verdict" in problems
    assert f"{SCHEMA_MISSING}: summary.unexplained" in problems
    assert f"{SCHEMA_MISSING}: summary.relative" in problems
    assert f"{SCHEMA_MISSING}: factors[0].layer" in problems


def test_schema_values_outside_prompt_lists():
    r = cause_report(verdict="mostly_explained", relative_verdict="same",
                     factors=[factor(size_fit="medium", stance="up", layer="market",
                                     sources=[source(match="related")])])
    problems = check_schema(r)
    assert all(code_of(p) == SCHEMA_VALUE for p in problems)
    assert {p.split(":", 1)[1].split("=")[0].strip() for p in problems} == {
        "verdict", "relative_verdict", "factors[0].size_fit", "factors[0].stance",
        "factors[0].layer", "factors[0].sources[0].match"}


def test_schema_bool_fields_reject_strings():
    """"false" 문자열을 참으로 받으면 뜻이 뒤집힌다(적재 모듈 _as_bool 과 같은 이유)."""
    r = cause_report(factors=[factor(direction_match="true", unconfirmed="false")])
    assert codes(check_schema(r)) == {SCHEMA_TYPE}


def test_schema_counter_and_relative_null_is_ok_but_others_cannot_be_empty():
    assert check_schema(cause_report()) == []
    assert check_schema(cause_report(summary=summary(relative="r", counter="c"))) == []
    r = cause_report(summary=summary(move=""))
    assert check_schema(r) == [f"{SCHEMA_VALUE}: summary.move 는 비울 수 없다"]
    r = cause_report(summary=summary(relative=1))
    assert codes(check_schema(r)) == {SCHEMA_TYPE}


def test_schema_background_needs_all_three_slots():
    r = cause_report(background={"bullish": [], "bearish": []})
    assert check_schema(r) == [f"{SCHEMA_MISSING}: background.neutral"]


def test_schema_background_items_are_objects_with_sources():
    """출처를 달아야 해서 문자열 항목은 받지 않는다. watch 는 붙일 때만 쓴다."""
    r = cause_report(background={"bullish": ["문자열 항목"], "bearish": [], "neutral": [bg()]})
    assert check_schema(r) == [f"{SCHEMA_TYPE}: background.bullish[0] 는 객체여야 한다(text·sources)"]
    no_sources = bg()
    del no_sources["sources"]
    r = cause_report(background={"bullish": [no_sources], "bearish": [],
                                 "neutral": [bg(watch="true")]})
    assert check_schema(r) == [
        f"{SCHEMA_MISSING}: background.bullish[0].sources",
        f"{SCHEMA_TYPE}: background.neutral[0].watch 는 true/false 여야 한다: 'true'"]


def test_schema_background_sources_share_factor_source_format():
    r = cause_report(background={"bullish": [bg(sources=[source(match="related")])],
                                 "bearish": [], "neutral": []})
    assert codes(check_schema(r)) == {SCHEMA_VALUE}


def event(placed="factors", **kw):
    return {"event": "3분기 영업이익이 예상을 밑돌았다", "dup_channels": 2, "placed": placed, **kw}


def test_events_missing_when_absent_or_report_unopened():
    assert check_events(cause_report()) == ("missing", [])
    assert check_events(None) == ("missing", [])


def test_events_passed():
    ok = [event(), event("summary.move", dup_channels=None), event("background"),
          event("background", reason="over_cap"), event("dropped", reason="off_topic"),
          event("dropped", reason="over_cap")]
    assert check_events(cause_report(events=ok)) == ("passed", [])
    assert check_events(cause_report(events=[])) == ("passed", [])


def test_events_schema_values():
    r = cause_report(events=[event("counter"), event("dropped", reason="single_source"),
                             event(dup_channels="2"), {"placed": "factors", "dup_channels": 1}])
    status, problems = check_events(r)
    assert status == "failed" and codes(problems) == {SCHEMA_VALUE, SCHEMA_TYPE, SCHEMA_MISSING}
    assert codes(check_events(cause_report(events="x"))[1]) == {SCHEMA_TYPE}
    assert codes(check_events(cause_report(events=[event(dup_channels=True)]))[1]) == {SCHEMA_TYPE}


@pytest.mark.parametrize("e", [
    event("dropped"),                              # dropped 인데 reason 없음
    event("factors", reason="over_cap"),           # reason 을 쓰지 않는 placed
    event("summary.move", reason="no_change"),
    event("background", reason="off_topic"),       # background 는 over_cap 만
])
def test_events_reason_condition(e):
    status, problems = check_events(cause_report(events=[e]))
    assert status == "failed" and codes(problems) == {EVENT_REASON_MISMATCH}


@pytest.mark.parametrize("events", [None, "x", [event("dropped")], [event("counter")]])
def test_events_never_affect_verify(events):
    """events 가 없거나 틀려도 판정은 그대로다. 보고서는 화면에 정상으로 나간다."""
    r = cause_report() if events is None else cause_report(events=events)
    assert verify(r, CAUSE) == ("passed", [])
    assert check_schema(r) == []


def test_schema_change_pct_must_be_number_not_bool():
    assert codes(check_schema(cause_report(change_pct=True))) == {SCHEMA_TYPE}
    assert codes(check_schema(cause_report(change_pct="-4.2"))) == {SCHEMA_TYPE}


# --- 규칙: move_case -----------------------------------------------------


def with_market(payload=None, *, change=None, **market):
    """payload 의 market 칸만 바꾼 사본. market=None 을 넘기면 market 자체가 null."""
    payload = payload or CAUSE
    out = {**payload, "change_pct": payload["change_pct"] if change is None else change}
    if "market" in market and market["market"] is None:
        out["market"] = None
    else:
        out["market"] = {**payload["market"], **market}
    return out


@pytest.mark.parametrize(("change", "median", "excess", "case"), [
    (0.45, 0.7, -0.25, "flat"),  # 등락률은 작고 차이도 작다
    (-2.5, -2.3, -0.2, "flat"),  # 등락률은 크지만 다른 대형주와 같이 빠졌다
    (-0.8, -3.5, 2.7, "opposite"),  # 내렸지만 다른 대형주보다 훨씬 덜 빠졌다
    (0.5, 3.0, -2.5, "opposite"),  # 올랐지만 다른 대형주보다 덜 올랐다
    (-4.2, -0.6, -3.6, "normal"),
    (2.0, 0.99, 1.01, "normal"),
    # 경계는 flat 에 포함
    (-3.0, -4.0, 1.0, "flat"), (3.0, 4.0, -1.0, "flat"),
    (-1.8, -2.81, 1.01, "opposite"), (1.8, 2.81, -1.01, "opposite"),
    # 0 처리: excess 0 은 flat, change 0 은 부호가 없어 opposite 가 아니라 normal
    (-3.0, -3.0, 0, "flat"), (0, -2.0, 2.0, "normal"), (0, 2.0, -2.0, "normal"),
    (-1.8, None, None, None),
])
def test_move_case(change, median, excess, case):
    payload = with_market(change=change, peer_median_pct=median, excess_pct=excess)
    assert move_case(payload) == case


def test_move_case_is_none_without_market():
    assert move_case(with_market(market=None)) is None
    assert move_case({k: v for k, v in CAUSE.items() if k != "market"}) is None


def test_move_case_ignores_value_already_in_input():
    """입력에 적힌 move_case 를 믿지 않는다. 판정은 한 곳에서만 한다."""
    assert move_case(with_market(FLAT, move_case="normal")) == "flat"


def test_fixture_cases():
    assert (move_case(CAUSE), move_case(FLAT), move_case(MARKET)) == ("normal", "flat", "opposite")


# ±1% 규칙 — 층마다 따로 본다. 등락 층은 |change_pct|, 상대 층은 |excess_pct|


def test_flat_day_with_cause_only_gets_flat_codes():
    """+0.45%, 중간값 +0.7%(excess -0.25). 두 층 모두 1 이하라 등락 층에 원인을 대면
    FLAT_MOVE 만 나온다. 상대 층은 판정·factor 가 규칙대로라 걸리지 않는다."""
    payload = with_market(change=0.45, peer_median_pct=0.7, excess_pct=-0.25)
    r = cause_report(change_pct=0.45, factors=[factor()])
    assert codes(check_rules(r, payload)) == {FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS}


def test_big_change_moving_with_peers_has_move_cause_but_no_relative():
    """-2.5% 에 다른 대형주가 -2.3% 면 상대 층은 flat 이다. 등락 층 원인(악재)은 댈 수 있다.
    다만 대형주와 같은 몫이 절반 이상이라 종목 고유 재료(직접)는 partial 까지다."""
    payload = with_market(change=-2.5, peer_median_pct=-2.3, excess_pct=-0.2)
    r = cause_report(change_pct=-2.5, verdict="partially_explained", factors=[factor("partial")])
    assert check_rules(r, payload) == []
    sufficient = cause_report(change_pct=-2.5, factors=[factor()])
    assert codes(check_rules(sufficient, payload)) == {MOVE_SUFFICIENT_STOCK_ONLY}
    as_relative = cause_report(change_pct=-2.5, verdict="no_clear_cause",
                               relative_verdict="explained", factors=[rel()])
    assert codes(check_rules(as_relative, payload)) == {FLAT_RELATIVE_VERDICT, FLAT_RELATIVE_FACTORS}


def test_small_change_with_peers_moving_a_lot_has_relative_cause_only():
    """-0.8% 에 다른 대형주가 -3.5% 면 등락 층은 flat, 상대 층(위쪽)은 호재로 설명한다."""
    payload = with_market(change=-0.8, peer_median_pct=-3.5, excess_pct=2.7)
    r = cause_report(change_pct=-0.8, verdict="no_clear_cause", relative_verdict="explained",
                     factors=[rel(stance="bullish")])
    assert check_rules(r, payload) == []


@pytest.mark.parametrize(("excess", "flagged"), [(-0.99, True), (-1.00, True), (-1.01, False)])
def test_relative_flat_rule_at_boundary(excess, flagged):
    r = cause_report(relative_verdict="explained", factors=[factor(), rel()])
    got = codes(check_rules(r, with_market(excess_pct=excess)))
    assert (got == {FLAT_RELATIVE_VERDICT, FLAT_RELATIVE_FACTORS}) is flagged
    assert got <= {FLAT_RELATIVE_VERDICT, FLAT_RELATIVE_FACTORS}


@pytest.mark.parametrize(("change", "flagged"), [(-0.99, True), (-1.00, True), (-1.01, False)])
def test_move_flat_rule_at_boundary(change, flagged):
    r = cause_report(change_pct=change, factors=[factor()])
    # 중간값을 작게 둬 시장 몫 규칙(MOVE_SUFFICIENT_STOCK_ONLY)과 섞이지 않게 한다
    got = codes(check_rules(r, with_market(change=change, peer_median_pct=-0.3)))
    assert (got == {FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS}) is flagged
    assert got <= {FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS}


def test_case_comes_from_input_not_report():
    """보고서가 등락률을 잘못 옮겨 적었다고 규칙을 피해 가면 안 된다."""
    r = cause_report(ticker="999980", date="2026-09-18", change_pct=-4.2)
    got = codes(check_rules(r, FLAT))
    assert {FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS, CHANGE_PCT_MISMATCH} <= got


def test_flat_move_with_empty_factors_but_wrong_verdict():
    r = flat_report(verdict="partially_explained")
    got = codes(check_rules(r, FLAT))
    assert FLAT_MOVE_VERDICT in got
    assert FLAT_MOVE_FACTORS not in got


def test_flat_relative_with_empty_factors_but_wrong_verdict():
    r = flat_report(relative_verdict="explained")
    got = codes(check_rules(r, FLAT))
    assert FLAT_RELATIVE_VERDICT in got
    assert FLAT_RELATIVE_FACTORS not in got


# 층의 값 — 등락 층은 change_pct, 상대 층은 excess_pct


@pytest.mark.parametrize(("payload", "move", "relative"), [
    (CAUSE, "-4.2", "-3.6"), (LESS_DOWN, "-0.39", "2.02"), (UP_NO_CAUSE, "0.54", "2.95"),
    (TWO_LAYERS, "-1.2", "1.21"), (MORE_DOWN, "-7.0", "-5.5"),
    (with_market(MARKET, excess_pct=None), "-1.8", None),  # 상대 층을 판단하지 않는다
    (with_market(MARKET, market=None), "-1.8", None),
])
def test_layer_pct(payload, move, relative):
    assert str(layer_pct(payload, "move")) == move
    got = layer_pct(payload, "relative")
    assert (None if got is None else str(got)) == relative


def less_down_report(**kw):
    """덜 내린 날(-0.39%, 중간값 -2.41%, excess +2.02). 등락 층은 flat 이고
    공급 계약 호재가 상대 층 원인이다."""
    return cause_report(**{
        "date": "2026-09-22", "change_pct": -0.39, "verdict": "no_clear_cause",
        "relative_verdict": "explained",
        "factors": [rel(stance="bullish", sources=[msg_source(LESS_DOWN, 0, 30)])],
        "background": {"bullish": [], "bearish": [], "neutral": []}, **kw})


def test_less_down_day_relative_bullish_factor_passes():
    assert verify(less_down_report(), LESS_DOWN) == ("passed", [])


def test_less_down_day_relative_direction_by_change_pct_fails():
    """상대 층 direction_match 를 종목 등락률(하락) 기준으로 계산하면 틀린 값이다."""
    src = [msg_source(LESS_DOWN, 0, 30)]
    as_counter = less_down_report(factors=[rel(stance="bullish", direction_match=False, sources=src)])
    assert codes(check_rules(as_counter, LESS_DOWN)) == {DIRECTION_MISMATCH, DIRECTION_MATCH_WRONG}
    bearish = less_down_report(factors=[rel(stance="bearish", sources=src)])
    assert codes(check_rules(bearish, LESS_DOWN)) == {DIRECTION_MATCH_WRONG}


def test_less_down_day_move_factor_fails():
    """-0.39% 는 등락 층 ±1% 이내다. 같은 호재를 move 로 넣으면 떨어진다."""
    src = [msg_source(LESS_DOWN, 0, 30)]
    r = less_down_report(verdict="explained", relative_verdict="no_clear_cause",
                         factors=[factor(stance="bullish", direction_match=False, sources=src)])
    got = codes(check_rules(r, LESS_DOWN))
    assert {FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS} <= got
    assert families_of(check_rules(r, LESS_DOWN)) == {FLAT_MOVE, DIRECTION_MISMATCH}


def test_less_down_day_bullish_only_in_counter_fails():
    """실제 사례: 호재를 출처 없이 counter 에만 적고 background 는 비웠다."""
    r = less_down_report(relative_verdict="no_clear_cause", factors=[],
                         summary=summary(counter="공급 계약 체결 공시가 있었습니다."))
    status, problems = verify(r, LESS_DOWN)
    assert status == "failed"
    assert codes(problems) == {COUNTER_WITHOUT_BACKGROUND}


def test_counter_backed_by_background_passes():
    r = less_down_report(relative_verdict="no_clear_cause", factors=[],
                         summary=summary(counter="공급 계약 체결 공시가 있었습니다."),
                         background={"bullish": [bg("공급 계약", [msg_source(LESS_DOWN, 0, 30)])],
                                     "bearish": [], "neutral": []})
    assert verify(r, LESS_DOWN) == ("passed", [])


def up_no_cause_report(**kw):
    return cause_report(**{
        "ticker": "999980", "name": "하늬결화학", "date": "2026-09-22", "change_pct": 0.54,
        "verdict": "no_clear_cause", "relative_verdict": "no_clear_cause", "factors": [],
        "background": {"bullish": [], "bearish": [], "neutral": []},
        "not_found": ["이 종목을 직접 다룬 메시지가 없다"], **kw})


def test_up_without_cause_passes_with_empty_factors():
    """재료 없이 오른 날(+0.54, excess +2.95). 상대 층은 ±1% 밖이지만 원인이 없으면 없다고 쓴다."""
    assert verify(up_no_cause_report(), UP_NO_CAUSE) == ("passed", [])


def test_up_without_cause_move_factor_fails():
    """+0.54% 는 등락 층 ±1% 이내다. move factor 가 있으면 떨어진다."""
    r = up_no_cause_report(verdict="partially_explained", factors=[
        factor("partial", [msg_source(UP_NO_CAUSE, 0, 20)], stance="bullish")])
    assert families_of(verify(r, UP_NO_CAUSE)[1]) == {FLAT_MOVE}


def test_market_driven_day_bearish_material_is_a_move_cause_not_relative():
    """-1.8% 에 excess +1.4. 2대 주주 지분 처분(악재)은 등락 층 원인은 되지만
    상대 층(위쪽) 원인은 될 수 없다. 중간값 -3.2% 가 등락 전부를 넘어 종목 고유 재료는 partial 까지다."""
    src = msg_source(MARKET, 0, 20)
    empty = {"bullish": [], "bearish": [], "neutral": []}
    as_move = cause_report(date="2026-09-21", change_pct=-1.8, verdict="partially_explained",
                           factors=[factor("partial", sources=[src])], background=empty)
    assert verify(as_move, MARKET) == ("passed", [])
    as_relative = cause_report(date="2026-09-21", change_pct=-1.8, verdict="no_clear_cause",
                               relative_verdict="explained", factors=[rel(sources=[src])])
    assert codes(check_rules(as_relative, MARKET)) == {DIRECTION_MATCH_WRONG}


# 덜 내린 하락일 — 두 층에 원인이 하나씩


def two_layers_report(**kw):
    """-1.2%, 중간값 -2.41%, excess +1.21. 업종 악재(간접)가 등락 층, 자사주 매입
    호재(직접)가 상대 층 원인이다."""
    sector, buyback = msg_source(TWO_LAYERS, 0, 30), msg_source(TWO_LAYERS, 1, 30)
    return cause_report(**{
        "date": "2026-09-23", "change_pct": -1.2,
        "verdict": "partially_explained", "relative_verdict": "explained",
        "summary": summary(relative="자사주 매입 공시로 덜 내렸습니다."),
        "factors": [factor("partial", [sector]), rel(stance="bullish", sources=[buyback])],
        "background": {"bullish": [], "bearish": [], "neutral": []}, **kw})


def test_two_layers_day_both_factors_pass():
    assert verify(two_layers_report(), TWO_LAYERS) == ("passed", [])


def test_two_layers_day_bearish_as_relative_fails_direction():
    """업종 악재를 relative 로 넣으면 상대 층 방향(위)과 어긋난다."""
    sector, buyback = msg_source(TWO_LAYERS, 0, 30), msg_source(TWO_LAYERS, 1, 30)
    claimed_match = two_layers_report(verdict="no_clear_cause", factors=[
        rel("partial", [sector]), rel(stance="bullish", sources=[buyback])])
    assert codes(check_rules(claimed_match, TWO_LAYERS)) == {DIRECTION_MATCH_WRONG}
    honest = two_layers_report(verdict="no_clear_cause", factors=[
        rel("partial", [sector], direction_match=False), rel(stance="bullish", sources=[buyback])])
    assert codes(check_rules(honest, TWO_LAYERS)) == {DIRECTION_MISMATCH}


def test_two_layers_day_bullish_as_move_fails_direction():
    """자사주 매입 호재를 move 로 넣으면 등락 층 방향(아래)과 어긋난다."""
    sector, buyback = msg_source(TWO_LAYERS, 0, 30), msg_source(TWO_LAYERS, 1, 30)
    r = two_layers_report(verdict="partially_explained", relative_verdict="no_clear_cause", factors=[
        factor("partial", [sector]), factor("partial", stance="bullish", sources=[buyback])])
    assert codes(check_rules(r, TWO_LAYERS)) == {DIRECTION_MATCH_WRONG}


# 시장보다 더 내린 날 — 두 층 모두 아래


def more_down_report(**kw):
    """-7.0%, 중간값 -1.5%, excess -5.5. 업종 악재(간접)가 등락 층, 고객사 공급사
    제외(직접)가 상대 층 원인이다."""
    customer, sector = msg_source(MORE_DOWN, 0, 30), msg_source(MORE_DOWN, 1, 20)
    return cause_report(**{
        "date": "2026-09-24", "change_pct": -7.0,
        "verdict": "partially_explained", "relative_verdict": "explained",
        "summary": summary(relative="최대 고객사 공급사에서 빠져 더 내렸습니다."),
        "factors": [rel(sources=[customer]), factor("partial", [sector])],
        "background": {"bullish": [], "bearish": [], "neutral": []}, **kw})


def test_more_down_day_both_layers_bearish_pass():
    assert verify(more_down_report(), MORE_DOWN) == ("passed", [])


@pytest.mark.parametrize("layer", ["move", "relative"])
def test_more_down_day_bullish_fails_in_either_layer(layer):
    sector = msg_source(MORE_DOWN, 1, 20)
    r = more_down_report(verdict="partially_explained" if layer == "move" else "no_clear_cause",
                         factors=[rel(sources=[msg_source(MORE_DOWN, 0, 30)]),
                                  factor("partial", [sector], layer=layer, stance="bullish")])
    assert codes(check_rules(r, MORE_DOWN)) == {DIRECTION_MATCH_WRONG}


# null — excess_pct 가 없으면 상대 층을 판단하지 않는다


@pytest.mark.parametrize("payload", [
    with_market(MARKET, excess_pct=None), with_market(MARKET, market=None)])
def test_null_market_judges_move_layer_only(payload):
    """-1.8% 하락의 원인으로 악재를 대면 통과한다. 상대 층 원인은 댈 수 없다.
    중간값이 남아 있는 경우가 있어 종목 고유 재료는 partial 로 둔다(시장 몫 규칙)."""
    src = msg_source(MARKET, 0, 20)
    r = cause_report(date="2026-09-21", change_pct=-1.8, verdict="partially_explained",
                     factors=[factor("partial", sources=[src])])
    assert check_rules(r, payload) == []
    with_relative = cause_report(date="2026-09-21", change_pct=-1.8, verdict="partially_explained",
                                 relative_verdict="explained",
                                 factors=[factor("partial", sources=[src]), rel(sources=[src])])
    assert codes(check_rules(with_relative, payload)) == {FLAT_RELATIVE_VERDICT, FLAT_RELATIVE_FACTORS}


def test_null_market_small_change_is_flat():
    r = flat_report(verdict="explained", factors=[factor(stance="bullish", sources=[msg_source(FLAT)])])
    got = codes(check_rules(r, with_market(FLAT, market=None)))
    assert got == {FLAT_MOVE_VERDICT, FLAT_MOVE_FACTORS}


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
    """두 층에 같은 표를 쓴다. 각 판정은 그 층의 factor 만 본다 — 다른 층에 sufficient
    가 있어도 이 층 판정을 explained 로 만들지 못한다."""
    r = cause_report(verdict=verdict, relative_verdict="explained",
                     factors=[factor(fit) for fit in fits] + [rel()])
    assert (VERDICT_SIZE_FIT not in codes(check_rules(r, CAUSE))) is ok
    r = cause_report(verdict="explained", relative_verdict=verdict,
                     factors=[factor()] + [rel(fit) for fit in fits])
    got = codes(check_rules(r, CAUSE))
    assert (RELATIVE_VERDICT_SIZE_FIT not in got) is ok
    assert VERDICT_SIZE_FIT not in got


def _without_size_fit():
    f = factor()
    del f["size_fit"]
    return f


@pytest.mark.parametrize(("case", "report", "schema_code"), [
    ("size_fit 누락", cause_report(factors=[_without_size_fit()]), SCHEMA_MISSING),
    ("size_fit 목록 밖", cause_report(factors=[factor("medium")]), SCHEMA_VALUE),
    ("size_fit null", cause_report(factors=[factor(None)]), SCHEMA_VALUE),
    ("verdict 목록 밖", cause_report(verdict="mostly_explained"), SCHEMA_VALUE),
    ("relative_verdict 목록 밖",
     cause_report(relative_verdict="same", factors=[factor(), rel()]), SCHEMA_VALUE),
    # layer 가 깨지면 factor 를 층으로 가를 수 없다. 두 층 모두 건너뛴다
    ("layer 목록 밖", cause_report(relative_verdict="explained",
                                 factors=[factor(layer="market")]), SCHEMA_VALUE),
    ("factors 가 배열 아님", cause_report(factors={"claim": "c"}), SCHEMA_TYPE),
    ("factor 가 객체 아님", cause_report(factors=["원인 한 줄"]), SCHEMA_TYPE),
])
def test_verdict_table_is_skipped_when_its_inputs_break_schema(case, report, schema_code):
    """판정 재료가 스키마를 어기면 스키마 실패로만 센다. 같은 원인을 두 번 세지 않는다."""
    status, problems = verify(report, CAUSE)
    assert status == "failed", case
    assert schema_code in codes(problems), case
    assert not {VERDICT_SIZE_FIT, RELATIVE_VERDICT_SIZE_FIT} & codes(problems), case


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


def test_background_sources_are_grounded_like_factors():
    bad_quote = cause_report(background={"bullish": [], "bearish": [], "neutral": [
        bg(sources=[source(INDIRECT_URL, "지어낸 문장", "indirect")])]})
    assert check_grounding(bad_quote, CAUSE) == [
        f"{QUOTE_NOT_IN_SOURCE}: background.neutral[0].sources[0] '지어낸 문장'"]
    bad_url = cause_report(background={"bullish": [], "bearish": [], "neutral": [
        bg(sources=[source("https://t.me/sample_channel_b/999", INDIRECT_QUOTE, "indirect")])]})
    assert URL_NOT_IN_INPUT in codes(check_grounding(bad_url, CAUSE))


def test_background_without_source_fails():
    r = cause_report(background={"bullish": [bg(sources=[])], "bearish": [], "neutral": []})
    assert check_grounding(r, CAUSE) == [f"{BACKGROUND_WITHOUT_SOURCE}: background.bullish[0]"]


def test_sources_at_most_three():
    three = cause_report(factors=[factor(sources=[source()] * 3)])
    assert check_grounding(three, CAUSE) == []
    four = cause_report(factors=[factor(sources=[source()] * 4)])
    assert check_grounding(four, CAUSE) == [f"{SOURCES_OVER_MAX}: factors[0] 4개 (최대 3)"]
    bg_four = cause_report(background={"bullish": [], "bearish": [], "neutral": [
        bg(sources=[source(INDIRECT_URL, INDIRECT_QUOTE, "indirect")] * 4)]})
    assert codes(check_grounding(bg_four, CAUSE)) == {SOURCES_OVER_MAX}


def test_verify_does_not_mutate_inputs():
    r, payload = cause_report(), copy.deepcopy(CAUSE)
    before = copy.deepcopy(r)
    verify(r, payload)
    assert r == before and payload == CAUSE


# 크게 오르고 다른 대형주보다도 크게 오른 날 — 같은 호재가 두 층에


def big_up_report(**kw):
    """+6.5%, 중간값 -0.6%, excess +7.1. 공급 계약 호재(직접) 하나가 두 층의 답이다.
    층마다 factor 를 하나씩 두고 출처는 같다(2부 3단계)."""
    contract = msg_source(BIG_UP, 0, 30)
    return cause_report(**{
        "date": "2026-09-25", "change_pct": 6.5,
        "verdict": "explained", "relative_verdict": "explained",
        "summary": summary(relative="같은 공급 계약 소식으로 다른 대형주보다 크게 올랐습니다."),
        "factors": [factor(stance="bullish", sources=[contract]),
                    rel(stance="bullish", sources=[contract])],
        "background": {"bullish": [], "bearish": [], "neutral": []}, **kw})


def test_same_event_in_both_layers_passes():
    assert verify(big_up_report(), BIG_UP) == ("passed", [])


# 하락 대부분이 시장 몫인 날 — 종목 고유 재료는 partial 까지


def market_share_report(size_fit="partial", sources=None, **kw):
    """-3.57%, 중간값 -2.62%, excess -0.95. 공장 보수(직접) 하나를 등락 층 원인으로 댄다.
    상대 층은 ±1% 이내라 비어 있다."""
    plant = msg_source(MARKET_SHARE, 0, 30)
    verdict = "explained" if size_fit == "sufficient" else "partially_explained"
    return cause_report(**{
        "ticker": "999980", "name": "하늬결화학", "date": "2026-09-25", "change_pct": -3.57,
        "verdict": verdict, "relative_verdict": "no_clear_cause",
        "factors": [factor(size_fit, sources if sources is not None else [plant])],
        "background": {"bullish": [], "bearish": [], "neutral": []}, **kw})


def test_market_share_day_stock_only_sufficient_fails():
    status, problems = verify(market_share_report("sufficient"), MARKET_SHARE)
    assert status == "failed" and codes(problems) == {MOVE_SUFFICIENT_STOCK_ONLY}


def test_market_share_day_stock_only_partial_passes():
    assert verify(market_share_report("partial"), MARKET_SHARE) == ("passed", [])


def test_market_share_day_with_market_material_can_be_sufficient():
    """간접(시장·업종) 출처가 섞인 factor 는 종목 고유 재료가 아니다. 시장 사건이 주된 원인이면
    sufficient 가 될 수 있다. 종목 고유 재료가 함께 sufficient 여도 통과다."""
    plant, selloff = msg_source(MARKET_SHARE, 0, 30), msg_source(MARKET_SHARE, 1, 30)
    mixed = market_share_report("sufficient", [plant, selloff])
    assert codes(check_rules(mixed, MARKET_SHARE)) == set()
    both = market_share_report("sufficient")
    both["factors"].append(factor("sufficient", [plant, selloff]))
    assert codes(check_rules(both, MARKET_SHARE)) == set()


@pytest.mark.parametrize("change, peer, fails", [
    (-4.0, -2.0, True),     # 정확히 절반 — 경계 포함
    (-4.0, -1.99, False),   # 절반 미만
    (-3.57, 2.62, False),   # 부호가 반대면 같은 몫이 아니다
    (6.5, -0.6, False),     # BIG_UP
    (-3.0, None, False),    # 중간값을 모른다
])
def test_market_share_threshold(change, peer, fails):
    payload = {**MARKET_SHARE, "change_pct": change,
               "market": {**MARKET_SHARE["market"], "peer_median_pct": peer}}
    report = market_share_report("sufficient", change_pct=change)
    report["factors"][0]["stance"] = "bearish" if change < 0 else "bullish"
    assert (MOVE_SUFFICIENT_STOCK_ONLY in codes(check_rules(report, payload))) is fails


def test_market_share_rule_skips_flat_move_day():
    """±1% 날 move factor 는 FLAT_MOVE_FACTORS 로 떨어진다. 같은 실수를 두 번 세지 않는다."""
    payload = {**MARKET_SHARE, "change_pct": -0.9,
               "market": {**MARKET_SHARE["market"], "peer_median_pct": -0.8}}
    report = market_share_report("sufficient", change_pct=-0.9)
    assert MOVE_SUFFICIENT_STOCK_ONLY not in codes(check_rules(report, payload))


def test_is_stock_specific():
    assert is_stock_specific(factor()) is True
    assert is_stock_specific(factor(sources=[source(), source(INDIRECT_URL, INDIRECT_QUOTE,
                                                              "indirect")])) is False
    assert is_stock_specific(factor(sources=[])) is False


# --- 래퍼 단위 판정 -------------------------------------------------------


def test_verify_wrapper_codes_for_unreadable_reports():
    assert verify_wrapper({"is_error": True, "error_code": LLM_ERROR, "error": "HTTP 429"},
                          None, CAUSE) == ("failed", [f"{LLM_ERROR}: HTTP 429"])
    status, problems = verify_wrapper(
        {"is_error": True, "error_code": EMPTY_RESPONSE, "error": "빈 응답"}, None, CAUSE)
    assert status == "failed" and codes(problems) == {EMPTY_RESPONSE}
    status, problems = verify_wrapper(
        {"is_error": True, "error_code": OUTPUT_TRUNCATED, "error": "출력 상한에서 잘림"},
        None, CAUSE)
    assert status == "failed" and codes(problems) == {OUTPUT_TRUNCATED}
    status, problems = verify_wrapper(
        {"is_error": False, "json_status": "invalid", "asked_question": True}, None, CAUSE)
    assert status == "failed" and codes(problems) == {JSON_INVALID, ASKED_QUESTION}
    assert verify_wrapper({"is_error": False, "json_status": "clean"}, cause_report(),
                          CAUSE) == ("passed", [])


# --- 계열 집계 ------------------------------------------------------------


def _flat_source():
    m = FLAT["messages"][0]
    return source(m["url"], m["text"][:15])


@pytest.mark.parametrize(("verdict", "fits"), [
    ("no_clear_cause", ["partial"]),  # FLAT_MOVE_FACTORS + VERDICT_SIZE_FIT
    ("partially_explained", []),  # FLAT_MOVE_VERDICT + VERDICT_SIZE_FIT
    ("partially_explained", ["sufficient"]),
    ("explained", ["partial"]),
])
def test_flat_day_verdict_table_counts_as_flat(verdict, fits):
    """flat 날의 판정표 위반은 언제나 FLAT 실수에 딸려 나온다."""
    r = flat_report(verdict=verdict, factors=[factor(fit, [_flat_source()]) for fit in fits])
    _, problems = verify(r, FLAT)
    assert VERDICT_SIZE_FIT in codes(problems)
    assert families_of(problems) == {FLAT_MOVE}


@pytest.mark.parametrize(("verdict", "fits"), [
    ("no_clear_cause", ["partial"]),
    ("partially_explained", []),
    ("explained", ["partial"]),
])
def test_flat_relative_day_verdict_table_counts_as_flat(verdict, fits):
    """상대 층도 같다. 상대 층 판정표 위반은 FLAT_RELATIVE 에 딸려 나온다."""
    r = flat_report(relative_verdict=verdict,
                    factors=[rel(fit, [_flat_source()]) for fit in fits])
    _, problems = verify(r, FLAT)
    assert RELATIVE_VERDICT_SIZE_FIT in codes(problems)
    assert families_of(problems) == {FLAT_RELATIVE}


def test_flat_in_one_layer_does_not_hide_other_layer_table():
    """등락 층이 flat 이어도 상대 층 판정표 위반은 그대로 센다. 층마다 따로 본다."""
    r = less_down_report(relative_verdict="partially_explained")  # relative 에 sufficient 가 있다
    problems = check_rules(r, LESS_DOWN)
    assert codes(problems) == {RELATIVE_VERDICT_SIZE_FIT}
    assert families_of(problems + [f"{FLAT_MOVE_VERDICT}: x"]) == {FLAT_MOVE, RELATIVE_VERDICT_SIZE_FIT}


def test_verdict_table_is_kept_on_normal_day():
    r = cause_report(verdict="partially_explained", factors=[factor("sufficient")])
    _, problems = verify(r, CAUSE)
    assert families_of(problems) == {VERDICT_SIZE_FIT}


def test_unrelated_codes_are_their_own_family():
    assert families_of([f"{LLM_ERROR}: x", f"{QUOTE_NOT_IN_SOURCE}: y", f"{QUOTE_NOT_IN_SOURCE}: z"])         == {LLM_ERROR, QUOTE_NOT_IN_SOURCE}
