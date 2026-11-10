"""보합·다른 방향 비교 종목이 섞인 동종 그룹의 relative 문장.

그룹 등락률(중앙값)은 보합이나 다른 방향 종목까지 넣어 낸 값이다. 현대차 0.00·기아 +1.00 이면 "대체로 0.50% 안팎 오른
현대차·기아" 가 되어 보합인 현대차도 오른 것처럼 읽혔다. 판정은 그대로 두고, 문장에는 그룹 등락률과 방향이 같은 종목만 각자의
등락률로 쓰고 나머지는 따로 한 문장으로 쓴다(market_compare.sentence_members, generate._canned_relative). 그 종목들로 다시
판정해 원래 판정과 다르면 판정하는 말 없이 등락만 쓴다. LLM 이 쓴 비교 종목 등락률은 COMPARE_MEMBER_RATE 가 입력과 대조한다.

그룹은 대상 현대모비스와 비교 종목 현대차·기아·현대위아로 만든 시험용이다(실제 그룹 정의가 아니다). 코스피는 0.62% 로 둔다.
"""

import itertools
from collections import Counter

import pytest

from app.services.market_data.context import build_market_context, kospi_relation
from app.services.stock_analysis import generate as gen
from app.services.stock_analysis import market_compare as mc
from app.services.stock_analysis.verify import (
    COMPARE_KOSPI_CONTRAST,
    COMPARE_KOSPI_RATE_IN_RELATIVE,
    COMPARE_MEMBER_RATE,
    COMPARE_META_PHRASE,
    COMPARE_MIXED_GROUP_RATE,
    COMPARE_MIXED_NOT_STATED,
    COMPARE_OPPOSITE_WORDING,
    COMPARE_TARGET_RATE_MISSING,
    check_warnings,
    code_of,
    verify,
)
from tests.test_market_data_context import DAY, KOSPI, STOCKS, kospi, stock

TARGET = "012330"
MEMBERS = [("005380", "현대차"), ("000270", "기아"), ("011210", "현대위아")]
KOSPI_RATE = 0.62
COMPARE_WARNINGS = {COMPARE_META_PHRASE, COMPARE_OPPOSITE_WORDING, COMPARE_MIXED_GROUP_RATE, COMPARE_MEMBER_RATE,
                    COMPARE_TARGET_RATE_MISSING, COMPARE_KOSPI_CONTRAST, COMPARE_MIXED_NOT_STATED,
                    COMPARE_KOSPI_RATE_IN_RELATIVE}


def _ctx(target: float, peers: list[float], kospi_rate: float = KOSPI_RATE):
    members = MEMBERS[:len(peers)]
    groups = {"자동차": {TARGET: "현대모비스", **dict(members)}}
    stocks = [stock(TARGET, 100, target)] + [stock(code, 100, rate) for (code, _), rate in zip(members, peers)]
    ctx = build_market_context(TARGET, DAY, kospi(kospi_rate), stocks, groups=groups, stock_groups={TARGET: ("자동차",)})
    return ctx, groups


def _payload(target: float, peers: list[float], kospi_rate: float = KOSPI_RATE) -> dict:
    ctx, groups = _ctx(target, peers, kospi_rate)
    compare = mc.to_input(ctx, groups=groups)
    excess = round(target - kospi_rate, 2)
    # 시험용 시장이라 코스피 비중·기여도는 의미가 없다. 대상과 코스피 등락률로 판정만 맞춘다
    compare["kospi"] = {
        "stock_change_rate_pct": target, "kospi_change_rate_pct": kospi_rate, "excess_vs_kospi_pp": excess,
        "kospi_weight_pct": 0.7, "kospi_contribution_pp": 0.0, "kospi_ex_self_change_rate_pct": kospi_rate,
        "excess_vs_kospi_ex_self_pp": excess, "kospi_basis": "kospi",
        "kospi_relation": kospi_relation(excess, target, kospi_rate)}
    return _report_input("현대모비스", TARGET, target, kospi_rate, compare)


def _report_input(name: str, code: str, change: float, kospi_rate: float, compare: dict) -> dict:
    return {
        "stock": name, "code": code, "target_date": DAY.isoformat(), "cutoff": f"{DAY.isoformat()}T15:30:00+09:00",
        "change_pct": change,
        "market": {"index": "코스피", "change_pct": kospi_rate, "as_of": "15:30", "url": "", "peer_median_pct": 0.84,
                   "peer_up": 12, "peer_down": 7, "peer_total": 20, "excess_pct": round(change - 0.84, 2)},
        "messages": [{"channel": "c", "url": "https://t.me/c/1", "datetime_kst": f"{DAY.isoformat()}T15:00:00+09:00",
                      "text": "코스피 마감 시황", "mention": "not_mentioned", "kind": "market_recap"}],
        "market_compare": compare,
    }


def _compare_warnings(report: dict, payload: dict) -> set[str]:
    return {code_of(w) for w in check_warnings(report, payload)} & COMPARE_WARNINGS


# --- 문장에 쓸 종목과 판정하는 말 (market_compare.sentence_members) ----------------------------------------------

@pytest.mark.parametrize(("target", "peers", "relation", "in_sentence", "judge"), [
    # 보합 하나·오른 하나. 중앙값 0.50 은 오른 쪽이라 기아만 문장에 쓴다
    (3.00, [0.00, 1.00], "diverges", [False, True], True),  # 기아(+1.00)와도 2.00%p 차이라 diverges 그대로
    (1.80, [0.00, 1.00], "diverges", [False, True], False),  # 기아와는 0.80%p 차이라 다시 판정하면 follows
    (0.50, [0.00, 1.00], "follows", [False, True], True),
    (0.60, [0.00, 3.00], "follows", [False, True], False),  # 기아(+3.00)와는 2.40%p 차이라 다시 판정하면 diverges
    (-0.30, [0.00, 0.80], "opposite", [False, True], False),  # opposite 는 원래 판정하는 말을 쓰지 않는다
    (3.00, [1.00, 1.20, 0.00], "diverges", [True, True, False], True),
    # 중앙값이 보합이면 보합인 종목을 문장에 쓴다
    (1.00, [0.00, 0.00, 2.00], "follows", [True, True, False], True),
    # 과반 예외로 follows(오른 둘·내린 하나). 내린 현대위아는 문장에서 뺀다. 현대차·기아(중앙값 0.58)로도 follows
    (0.27, [0.35, 0.80, -1.37], "follows", [True, True, False], True),
    # 나눌 게 없다: 모두 같은 방향, 모두 보합, 비교 종목 하나
    (2.00, [0.50, 1.50], "follows", [True, True], True),
    (3.00, [0.00, 0.00], "diverges", [True, True], True),
    (2.01, [1.00], "inconclusive", [True], False),
    # 방향이 엇갈린 그룹(inconclusive)은 나누지 않는다 — 모든 종목을 각자의 등락률로 쓰고 엇갈렸다고 덧붙인다
    (2.50, [2.16, -0.83], "inconclusive", [True, True], False),
])
def test_sentence_members(target, peers, relation, in_sentence, judge) -> None:
    [peer] = _payload(target, peers)["market_compare"]["peers"]
    assert peer["relation"] == relation
    assert [m["in_sentence"] for m in peer["members_used"]] == in_sentence
    assert [m["change_rate_pct"] for m in peer["members_used"]] == peers
    # judge_in_sentence 는 판정하는 말을 쓰는 follows·diverges 에만 값이 있다. 엇갈린 그룹은 mixed 로 가른다
    assert peer["judge_in_sentence"] is (judge if relation in ("follows", "diverges") else None)
    assert peer["mixed"] is (relation == "inconclusive" and len(peers) >= 2)


# --- 정형 보고서 relative ---------------------------------------------------------------------------------------

@pytest.mark.parametrize(("target", "peers", "relative"), [
    # 기아와 비교해도 크게 달랐다 → 판정하는 말을 쓴다. 보합인 현대차는 따로
    (3.00, [0.00, 1.00],
     "현대모비스는 1.00% 오른 같은 자동차 그룹의 기아와 크게 달랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
    # 판정(diverges)은 중앙값 0.50 기준. 문장에 보이는 기아 +1.00 과는 0.80%p 라 "크게 달랐다" 를 쓰지 않고 등락만
    (1.80, [0.00, 1.00],
     "같은 자동차 그룹의 기아는 1.00% 올랐고, 현대모비스는 1.80% 올랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
    # 판정(follows)은 중앙값 1.50 기준. 기아 +3.00 과 "비슷하게" 라고 쓰지 않는다. 코스피는 따라갔으니 그 문장은 남긴다
    (0.60, [0.00, 3.00],
     ("현대모비스는 코스피와 비슷하게 움직여 시장 전체 흐름을 따라갔습니다. "
      "같은 자동차 그룹의 기아는 3.00% 올랐고, 현대모비스는 0.60% 올랐습니다. 같은 그룹의 현대차는 보합이었습니다.")),
    # 과반 예외 follows. 예전에는 "대체로 0.35% 안팎 오른 … 현대차·기아·현대위아" 로 내린 현대위아도 오른 것처럼 읽혔다
    (0.27, [0.35, 0.80, -1.37],
     ("현대모비스는 코스피, 그리고 0.35~0.80% 오른 같은 자동차 그룹의 현대차·기아와 비슷하게 움직여 시장 전체 흐름을 "
      "따라갔습니다. 같은 그룹의 현대위아는 1.37% 내렸습니다.")),
    (-0.30, [0.00, 0.80],
     "같은 자동차 그룹의 기아는 0.80% 올랐고, 현대모비스는 0.30% 내렸습니다. 같은 그룹의 현대차는 보합이었습니다."),
    (3.00, [1.00, 1.20, 0.00],
     "현대모비스는 1.00~1.20% 오른 같은 자동차 그룹의 현대차·기아와 크게 달랐습니다. 같은 그룹의 현대위아는 보합이었습니다."),
    # 나눌 게 없으면 지금처럼 그룹 등락률
    (3.00, [0.00, 0.00], "현대모비스는 대체로 보합인 같은 자동차 그룹의 현대차·기아와 크게 달랐습니다."),
])
def test_canned_relative(target, peers, relative) -> None:
    payload = _payload(target, peers)
    report = gen.canned_report(payload)
    assert report["summary"]["relative"] == relative
    assert verify(report, payload) == ("passed", [])
    assert _compare_warnings(report, payload) == set()


def test_kb_real_day_majority_group_sentence() -> None:
    """2026-10-27 KB금융(+0.27%) 실제 응답. 신한지주 +0.35·하나금융지주 +0.80·우리금융지주 −1.37 로 과반 예외 follows 다."""
    compare = mc.to_input(build_market_context("105560", DAY, KOSPI, STOCKS))
    payload = _report_input("KB금융", "105560", 0.27, compare["kospi"]["kospi_change_rate_pct"], compare)
    report = gen.canned_report(payload)
    assert report["summary"]["relative"] == (
        "KB금융은 코스피와는 다르게 0.35~0.80% 오른 같은 은행지주 그룹의 신한지주·하나금융지주와 함께 움직였습니다. "
        "같은 그룹의 우리금융지주는 1.37% 내렸습니다.")
    assert verify(report, payload) == ("passed", [])
    assert _compare_warnings(report, payload) == set()


# --- LLM 이 쓴 비교 종목 등락률 검증 (COMPARE_MEMBER_RATE) -------------------------------------------------------

@pytest.mark.parametrize(("target", "peers", "relative"), [
    # 기아는 +1.00
    (3.00, [0.00, 1.00], "현대모비스는 1.20% 오른 같은 자동차 그룹의 기아와 크게 달랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
    (3.00, [0.00, 1.00], "같은 자동차 그룹의 기아는 1.10% 올랐고, 현대모비스는 3.00% 올랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
    (3.00, [0.00, 1.00], "현대모비스는 같은 자동차 그룹의 기아(1.20%)와 크게 달랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
    # 방향이 반대
    (3.00, [0.00, 1.00], "현대모비스는 1.00% 내린 같은 자동차 그룹의 기아와 크게 달랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
    # 보합인 현대차를 오른 것처럼
    (3.00, [0.00, 1.00], "현대모비스는 1.00% 오른 같은 자동차 그룹의 기아와 크게 달랐습니다. 같은 그룹의 현대차는 0.50% 올랐습니다."),
    (3.00, [0.00, 1.00], "현대모비스는 1.00% 오른 같은 자동차 그룹의 현대차·기아와 크게 달랐습니다."),
    # 문장에서 빠지는 종목이 있는 그룹을 그룹 등락률로(이번 수정 전 문장)
    (3.00, [0.00, 1.00], "현대모비스는 대체로 0.50% 안팎 오른 같은 자동차 그룹의 현대차·기아와 크게 달랐습니다."),
    # 범위 끝값이 틀렸다(0.35~0.80 이어야 한다)
    (0.27, [0.35, 0.80, -1.37],
     ("현대모비스는 코스피, 그리고 0.35~1.37% 오른 같은 자동차 그룹의 현대차·기아와 비슷하게 움직여 시장 전체 흐름을 "
      "따라갔습니다. 같은 그룹의 현대위아는 1.37% 내렸습니다.")),
    # 내린 현대위아를 오른 것으로
    (0.27, [0.35, 0.80, -1.37],
     ("현대모비스는 코스피, 그리고 0.35~0.80% 오른 같은 자동차 그룹의 현대차·기아와 비슷하게 움직여 시장 전체 흐름을 "
      "따라갔습니다. 같은 그룹의 현대위아는 1.37% 올랐습니다.")),
    # 나눌 게 없는 그룹인데 그룹 등락률이 틀렸다(1.00 이어야 한다)
    (2.00, [0.50, 1.50], "현대모비스는 대체로 1.50% 안팎 오른 같은 자동차 그룹의 현대차·기아와 비슷하게 움직였습니다."),
])
def test_llm_wrong_member_rate_is_warned(target, peers, relative) -> None:
    payload = _payload(target, peers)
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert COMPARE_MEMBER_RATE in _compare_warnings(report, payload)


@pytest.mark.parametrize(("target", "peers", "relative"), [
    # 정형 문장과 꼴이 달라도 숫자가 맞으면 걸리지 않는다
    (3.00, [0.00, 1.00], "같은 자동차 그룹의 현대차는 보합이었고 기아는 1.00% 올랐습니다. 현대모비스는 3.00% 올랐습니다."),
    (0.27, [0.35, 0.80, -1.37],
     "같은 자동차 그룹의 현대차는 0.35%, 기아는 0.80% 올랐고 현대위아는 1.37% 내렸습니다."),
    (2.00, [0.50, 1.50], "현대모비스는 대체로 1.00% 안팎 오른 같은 자동차 그룹의 현대차·기아와 비슷하게 움직였습니다."),
])
def test_llm_right_member_rate_is_not_warned(target, peers, relative) -> None:
    payload = _payload(target, peers)
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert COMPARE_MEMBER_RATE not in _compare_warnings(report, payload)


def test_old_input_without_member_rates_is_not_checked() -> None:
    """종목별 등락률이 없는 예전 입력은 대조할 값이 없어 보지 않는다."""
    payload = _payload(3.00, [0.00, 1.00])
    for m in payload["market_compare"]["peers"][0]["members_used"]:
        del m["change_rate_pct"], m["in_sentence"]
    report = gen.canned_report(payload)
    report["summary"]["relative"] = "현대모비스는 1.20% 오른 같은 자동차 그룹의 기아와 크게 달랐습니다."
    assert COMPARE_MEMBER_RATE not in _compare_warnings(report, payload)


@pytest.mark.parametrize(("target", "peers", "relative"), [
    # judge_in_sentence false 인 그룹에 판정하는 말
    (1.80, [0.00, 1.00], "현대모비스는 1.00% 오른 같은 자동차 그룹의 기아와 크게 달랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
    (0.60, [0.00, 3.00],
     ("현대모비스는 코스피, 그리고 3.00% 오른 같은 자동차 그룹의 기아와 비슷하게 움직여 시장 전체 흐름을 따라갔습니다. "
      "같은 그룹의 현대차는 보합이었습니다.")),
])
def test_llm_judge_words_when_shown_members_disagree_are_warned(target, peers, relative) -> None:
    payload = _payload(target, peers)
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    warned = _compare_warnings(report, payload)
    assert COMPARE_OPPOSITE_WORDING in warned
    assert COMPARE_MEMBER_RATE not in warned  # 숫자는 맞다


# --- 판정하는 말을 쓰지 않는 그룹: unexplained 의 판정하는 말, relative 의 이 종목 등락률 ------------------------
# 2026-11-09 실제 LLM 실행([0.00, +1.00] → +1.80)에서 relative 는 등락만 썼지만 unexplained 에 "같은 자동차 그룹과 다르게 오른
# 이유" 를 썼고, relative 에서 이 종목 등락률(1.80%)을 빠뜨렸다.

LLM_UNEXPLAINED = ("대형주 전반과 비슷하게 움직였지만, 현대모비스가 같은 자동차 그룹과 다르게 오른 이유는 메시지에서 확인되지 "
                   "않습니다.")
LLM_RELATIVE_NO_TARGET = "코스피와 다르게 움직였습니다. 같은 자동차 그룹의 기아는 1.00% 올랐고, 현대차는 보합이었습니다."


@pytest.mark.parametrize(("target", "peers", "unexplained"), [
    (1.80, [0.00, 1.00], LLM_UNEXPLAINED),  # 실제 LLM 출력
    (1.80, [0.00, 1.00], "현대모비스가 같은 자동차 그룹 종목들과 달리 오른 이유는 메시지에서 확인되지 않습니다."),
    (1.80, [0.00, 1.00], "현대모비스가 기아와 다르게 움직인 이유는 메시지에서 확인되지 않습니다."),
    (1.80, [0.00, 1.00], "같은 그룹과 크게 달랐던 이유는 메시지에서 확인되지 않습니다."),
    (0.60, [0.00, 3.00], "현대모비스는 같은 자동차 그룹 흐름을 따라갔지만 그 이유는 메시지에서 확인되지 않습니다."),
    # 엇갈린 그룹(inconclusive, mixed)도 unexplained 에 그룹 판정을 쓰지 않는다 — 리뷰 예시
    (2.50, [2.16, -0.83], "현대모비스가 같은 자동차 그룹과 다르게 오른 이유는 메시지에서 확인되지 않습니다."),
])
def test_llm_unexplained_group_judgment_is_warned(target, peers, unexplained) -> None:
    payload = _payload(target, peers)
    peer = payload["market_compare"]["peers"][0]
    # 판정하는 말을 빼는 follows·diverges 그룹(false)과 엇갈린 그룹(null, mixed)
    assert peer["judge_in_sentence"] is False or (peer["judge_in_sentence"] is None and peer["mixed"])
    report = gen.canned_report(payload)
    report["summary"]["unexplained"] = unexplained
    warnings = [w for w in check_warnings(report, payload) if code_of(w) == COMPARE_OPPOSITE_WORDING]
    assert len(warnings) == 1
    assert "summary.unexplained" in warnings[0]


@pytest.mark.parametrize(("target", "peers", "unexplained"), [
    # 그룹 말이 없다. "대형주 전반과 비슷하게" 는 대형주 비교라 그대로 둔다
    (1.80, [0.00, 1.00], "대형주 전반과 비슷하게 움직였지만, 이를 설명할 사건은 메시지에서 확인되지 않습니다."),
    # judge_in_sentence 가 true 인 diverges 그룹은 지금처럼 unexplained 에 쓴다
    (3.00, [0.00, 1.00], "현대모비스가 같은 자동차 그룹과 다르게 오른 이유는 메시지에서 확인되지 않습니다."),
])
def test_unexplained_without_forbidden_group_judgment_is_not_warned(target, peers, unexplained) -> None:
    payload = _payload(target, peers)
    report = gen.canned_report(payload)
    report["summary"]["unexplained"] = unexplained
    assert _compare_warnings(report, payload) == set()


@pytest.mark.parametrize(("target", "peers", "relative"), [
    (1.80, [0.00, 1.00], LLM_RELATIVE_NO_TARGET),  # 실제 LLM 출력
    (0.60, [0.00, 3.00],
     ("현대모비스는 코스피와 비슷하게 움직여 시장 전체 흐름을 따라갔습니다. 같은 자동차 그룹의 기아는 3.00% 올랐습니다. "
      "같은 그룹의 현대차는 보합이었습니다.")),
])
def test_llm_missing_target_rate_is_warned(target, peers, relative) -> None:
    payload = _payload(target, peers)
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    warned = _compare_warnings(report, payload)
    assert warned == {COMPARE_TARGET_RATE_MISSING}  # 비교 종목 숫자·판정하는 말은 맞다


@pytest.mark.parametrize(("target", "peers", "relative"), [
    # 꼴이 달라도 이 종목 등락률이 있으면 된다("1.8%" 도 1.80)
    (1.80, [0.00, 1.00], "같은 자동차 그룹의 기아는 1.00% 올랐고 현대모비스는 1.8% 올랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
    # judge_in_sentence 가 true 면 판정하는 말로 쓰니 이 종목 등락률이 없어도 된다
    (3.00, [0.00, 1.00],
     "현대모비스는 1.00% 오른 같은 자동차 그룹의 기아와 크게 달랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
])
def test_target_rate_present_or_not_required_is_not_warned(target, peers, relative) -> None:
    payload = _payload(target, peers)
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert _compare_warnings(report, payload) == set()


# --- 코스피와 같은 방향인 날 반대를 잇는 말 (COMPARE_KOSPI_CONTRAST) ---------------------------------------------
# 2026-11-09 실제 LLM 실행(KB금융 2026-10-27, 코스피 +3.09·KB금융 +0.27, 코스피 diverges·그룹 follows)에서 둘 다 올랐는데
# "코스피는 올랐지만 KB금융은 … 함께 올랐습니다" 로 썼다. 방향이 같으면 "코스피와는 다르게" 로 쓴다.

LLM_KB_RELATIVE = ("코스피는 올랐지만 KB금융은 0.35~0.80% 오른 같은 은행지주 그룹의 신한지주·하나금융지주와 함께 올랐습니다. "
                   "같은 그룹의 우리금융지주는 1.37% 내렸습니다.")


def _kb_payload() -> dict:
    compare = mc.to_input(build_market_context("105560", DAY, KOSPI, STOCKS))
    return _report_input("KB금융", "105560", 0.27, compare["kospi"]["kospi_change_rate_pct"], compare)


@pytest.mark.parametrize(("key", "text"), [
    ("relative", LLM_KB_RELATIVE),  # 실제 LLM 출력
    ("move", "오후 3시 30분 장 마감 기준 코스피는 3.09% 올랐지만 KB금융은 0.27% 오르는 데 그쳤습니다."),
    ("relative", ("코스피가 오른 반면 KB금융은 0.35~0.80% 오른 같은 은행지주 그룹의 신한지주·하나금융지주와 함께 움직였습니다. "
                  "같은 그룹의 우리금융지주는 1.37% 내렸습니다.")),
])
def test_llm_kospi_contrast_on_same_direction_is_warned(key, text) -> None:
    payload = _kb_payload()
    kospi = payload["market_compare"]["kospi"]
    assert kospi["kospi_relation"] == "diverges" and kospi["stock_change_rate_pct"] > 0 and kospi["kospi_change_rate_pct"] > 0
    report = gen.canned_report(payload)
    report["summary"][key] = text
    warnings = [w for w in check_warnings(report, payload) if code_of(w) == COMPARE_KOSPI_CONTRAST]
    assert len(warnings) == 1 and f"summary.{key}" in warnings[0]
    assert _compare_warnings(report, payload) == {COMPARE_KOSPI_CONTRAST}  # 비교 종목 숫자는 맞다


def test_kospi_contrast_on_opposite_direction_is_not_warned() -> None:
    """방향이 다르면 "코스피는 올랐지만 이 종목은 내렸습니다" 가 맞는 꼴이다."""
    payload = _payload(-1.50, [-1.20, -1.40])
    assert payload["market_compare"]["kospi"]["kospi_relation"] == "diverges"
    report = gen.canned_report(payload)
    report["summary"]["move"] = "오후 3시 30분 장 마감 기준 코스피는 0.62% 올랐지만 현대모비스는 1.50% 내렸습니다."
    assert COMPARE_KOSPI_CONTRAST not in _compare_warnings(report, payload)


def test_kospi_same_direction_written_as_different_is_not_warned() -> None:
    payload = _kb_payload()
    report = gen.canned_report(payload)
    report["summary"]["relative"] = (
        "KB금융은 코스피와는 다르게 0.35~0.80% 오른 같은 은행지주 그룹의 신한지주·하나금융지주와 함께 움직였습니다. "
        "같은 그룹의 우리금융지주는 1.37% 내렸습니다.")
    assert _compare_warnings(report, payload) == set()


# --- 방향이 엇갈린 그룹: 종목별 등락률 + "방향이 엇갈려" (COMPARE_MIXED_NOT_STATED·COMPARE_MEMBER_RATE) -----------------
# 2026-11-09 실제 LLM 실행(리뷰 예시)에서 엇갈린 그룹을 종목별 등락률로 쓰고 엇갈렸다는 말을 뺐다. 종목별 등락률은 독자에게
# 정보가 되므로 규칙을 그쪽으로 바꾸고(정형 보고서도), 엇갈렸다는 말은 꼭 덧붙이게 한다.

MIXED_TAIL = "방향이 엇갈려 그룹 흐름과 비교하기 어렵습니다."


@pytest.mark.parametrize(("target", "peers", "relative"), [
    (2.50, [2.16, -0.83], f"같은 자동차 그룹의 현대차는 2.16% 올랐고 기아는 0.83% 내려, {MIXED_TAIL}"),  # 리뷰 예시
    (0.10, [1.00, 0.00, -1.00],
     ("현대모비스는 코스피와 비슷하게 움직여 시장 전체 흐름을 따라갔습니다. "
      f"같은 자동차 그룹의 현대차는 1.00% 올랐고 기아는 보합이었고 현대위아는 1.00% 내려, {MIXED_TAIL}")),
    (0.00, [-1.00, 1.00],
     ("현대모비스는 코스피와 비슷하게 움직여 시장 전체 흐름을 따라갔습니다. "
      f"같은 자동차 그룹의 현대차는 1.00% 내렸고 기아는 1.00% 올라, {MIXED_TAIL}")),
])
def test_canned_mixed_group_writes_member_rates_and_mixed_note(target, peers, relative) -> None:
    payload = _payload(target, peers)
    assert payload["market_compare"]["peers"][0]["relation"] == "inconclusive"
    report = gen.canned_report(payload)
    assert report["summary"]["relative"] == relative
    assert verify(report, payload) == ("passed", [])
    assert _compare_warnings(report, payload) == set()


def test_canned_mixed_group_old_input_without_rates_has_no_numbers() -> None:
    """종목별 등락률이 없는 입력(예전 형식)은 예전처럼 수치 없이 쓴다."""
    payload = _payload(2.50, [2.16, -0.83])
    for m in payload["market_compare"]["peers"][0]["members_used"]:
        del m["change_rate_pct"], m["in_sentence"]
    report = gen.canned_report(payload)
    assert report["summary"]["relative"] == f"같은 자동차 그룹의 현대차·기아는 {MIXED_TAIL}"


@pytest.mark.parametrize("relative", [
    # 실제 LLM 출력 두 회차 — 종목별 등락률은 맞지만 엇갈렸다는 말이 없다
    "현대모비스는 코스피와는 다르게 움직였습니다. 같은 자동차 그룹의 현대차는 2.16% 올랐고 기아는 0.83% 내렸습니다.",
    "현대모비스는 코스피와는 다르게 움직였고, 같은 자동차 그룹의 현대차는 2.16% 올랐으며 기아는 0.83% 내렸습니다.",
])
def test_llm_mixed_group_without_mixed_note_is_warned(relative) -> None:
    payload = _payload(2.50, [2.16, -0.83])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert _compare_warnings(report, payload) == {COMPARE_MIXED_NOT_STATED}


@pytest.mark.parametrize("relative", [
    # 다음 문장에 있어도 된다(2026-11-09 첫 실행의 출력)
    f"같은 자동차 그룹의 현대차는 2.16% 올랐고 기아는 0.83% 내렸습니다. 두 종목의 {MIXED_TAIL}",
    "같은 자동차 그룹의 현대차는 2.16% 올랐고 기아는 0.83% 내려 두 종목의 방향이 서로 달랐습니다.",
    f"같은 자동차 그룹의 현대차·기아는 {MIXED_TAIL}",  # 예전 꼴(수치 없음)도 규칙 위반은 아니다
])
def test_llm_mixed_group_with_mixed_note_is_not_warned(relative) -> None:
    payload = _payload(2.50, [2.16, -0.83])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert _compare_warnings(report, payload) == set()


@pytest.mark.parametrize("relative", [
    f"같은 자동차 그룹의 현대차는 2.61% 올랐고 기아는 0.83% 내려, {MIXED_TAIL}",  # 값이 틀림
    f"같은 자동차 그룹의 현대차는 2.16% 올랐고 기아는 0.83% 올라, {MIXED_TAIL}",  # 방향이 틀림
    f"같은 자동차 그룹의 현대차는 보합이었고 기아는 0.83% 내려, {MIXED_TAIL}",  # 오른 종목을 보합으로
    # 그룹 등락률(0.67%)은 엇갈린 그룹에 쓸 수 있는 수치가 아니다 — 예전에는 허용 수치에 들어 있었다
    f"같은 자동차 그룹의 현대차(2.16%)·기아(0.67%)는 {MIXED_TAIL}",
    f"같은 자동차 그룹의 현대차·기아는 대체로 0.67% 안팎 올라, {MIXED_TAIL}",
])
def test_llm_mixed_group_wrong_member_rate_is_warned(relative) -> None:
    payload = _payload(2.50, [2.16, -0.83])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert COMPARE_MEMBER_RATE in _compare_warnings(report, payload)


# --- relative 의 코스피 수치 (COMPARE_KOSPI_RATE_IN_RELATIVE) ------------------------------------------------------
# 2026-11-09 실제 LLM 실행([0.00, +1.00] → +1.80)에서 relative 에 "코스피는 0.62% 올랐고" 를 썼다. 코스피 수치는 move 에만 쓴다.

LLM_RELATIVE_KOSPI_RATE = ("코스피는 0.62% 올랐고 현대모비스는 1.8% 올라 코스피와는 다르게 움직였습니다. 같은 자동차 그룹의 기아는 "
                           "1.0% 올랐고 현대모비스는 1.8% 올랐습니다. 같은 그룹의 현대차는 보합이었습니다.")


@pytest.mark.parametrize("relative", [
    LLM_RELATIVE_KOSPI_RATE,  # 실제 LLM 출력
    ("현대모비스는 코스피(+0.62%)와는 다르게 움직였습니다. 같은 자동차 그룹의 기아는 1.00% 올랐고, 현대모비스는 1.80% "
     "올랐습니다. 같은 그룹의 현대차는 보합이었습니다."),
])
def test_llm_kospi_rate_in_relative_is_warned(relative) -> None:
    payload = _payload(1.80, [0.00, 1.00])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert _compare_warnings(report, payload) == {COMPARE_KOSPI_RATE_IN_RELATIVE}


def test_kospi_rate_in_member_sentence_is_warned_by_both() -> None:
    """비교 종목 문장에 코스피 수치가 섞이면 비교 종목 문장의 입력에 없는 수치(COMPARE_MEMBER_RATE)로도 걸린다."""
    payload = _payload(1.80, [0.00, 1.00])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = ("코스피 지수가 0.62% 오른 날 같은 자동차 그룹의 기아는 1.00% 올랐고, 현대모비스는 1.80% "
                                     "올랐습니다. 같은 그룹의 현대차는 보합이었습니다.")
    assert _compare_warnings(report, payload) == {COMPARE_KOSPI_RATE_IN_RELATIVE, COMPARE_MEMBER_RATE}


def test_group_rate_after_kospi_words_is_not_kospi_rate() -> None:
    """"코스피와는 다르게 0.35~0.80% 오른 …" 의 수치는 그룹 쪽이다. move 의 코스피 수치도 보지 않는다."""
    payload = _kb_payload()
    report = gen.canned_report(payload)
    assert "3.09%" in report["summary"]["move"]  # 코스피 수치는 move 에 있다
    report["summary"]["relative"] = (
        "KB금융은 코스피와는 다르게 0.35~0.80% 오른 같은 은행지주 그룹의 신한지주·하나금융지주와 함께 움직였습니다. "
        "같은 그룹의 우리금융지주는 1.37% 내렸습니다.")
    assert _compare_warnings(report, payload) == set()


# --- 리뷰 후속: 홀수 엇갈린 그룹의 중앙값, 대상 등락률을 찾는 범위, 정형 보고서 전수 점검 ------------------------------

def test_odd_mixed_group_median_is_a_member_rate_and_not_warned() -> None:
    """비교 종목이 홀수면 중앙값이 한 종목의 등락률이다. 현대차 +0.40 이 중앙값이라 예전에는 "현대차는 0.40% 올랐고" 가
    그룹 등락률로 잡혔다(COMPARE_MIXED_GROUP_RATE)."""
    payload = _payload(-0.60, [0.40, 1.20, -0.50])  # 현대차 +0.40·기아 +1.20·현대위아 −0.50
    [peer] = payload["market_compare"]["peers"]
    assert peer["relation"] == "inconclusive" and peer["mixed"] is True
    assert peer["median_change_rate_pct"] == 0.40
    report = gen.canned_report(payload)
    assert report["summary"]["relative"] == (
        f"같은 자동차 그룹의 현대차는 0.40%, 기아는 1.20% 올랐고 현대위아는 0.50% 내려, {MIXED_TAIL}")  # 같은 방향은 묶는다
    assert verify(report, payload) == ("passed", [])
    assert _compare_warnings(report, payload) == set()
    # LLM 이 다른 꼴로 맞게 써도 걸리지 않는다
    report["summary"]["relative"] = (f"같은 자동차 그룹의 현대차는 0.40%, 기아는 1.20% 올랐고 현대위아는 0.50% 내렸습니다. "
                                     f"세 종목의 {MIXED_TAIL}")
    assert _compare_warnings(report, payload) == set()


@pytest.mark.parametrize("relative", [
    # 틀린 것이 묶음 앞쪽 종목뿐이다. 수치(0.50)는 다른 비교 종목 등락률이라 "입력에 없는 수치" 로는 걸리지 않고,
    # 끝 종목(기아는 1.20% 올랐)은 맞아 이름 → 수치 꼴로도 걸리지 않는다
    f"같은 자동차 그룹의 현대차는 0.50%, 기아는 1.20% 올랐고 현대위아는 0.50% 내려, {MIXED_TAIL}",  # 현대차 값이 틀림
    f"같은 자동차 그룹의 현대위아는 0.50%, 기아는 1.20% 올랐고 현대차는 0.40% 올라, {MIXED_TAIL}",  # 내린 현대위아를 오른 묶음에
])
def test_llm_grouped_member_rates_are_checked_per_member(relative) -> None:
    """같은 방향 종목을 쉼표로 묶은 꼴("현대차는 0.40%, 기아는 1.20% 올랐고")도 종목마다 수치·방향을 대조한다."""
    payload = _payload(-0.60, [0.40, 1.20, -0.50])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert COMPARE_MEMBER_RATE in _compare_warnings(report, payload)


def test_target_rate_equal_to_member_rate_is_not_mistaken() -> None:
    """대상(+2.40)과 기아(+2.40)의 등락률이 같다. 그룹 문장에 기아 수치만 있어도 예전에는 relative 전체에서 2.40 을 찾아
    대상 등락률이 있는 것으로 봤다."""
    payload = _payload(2.40, [0.00, 2.40])  # 중앙값 1.20 기준 diverges, 기아와는 0.00%p 라 판정하는 말을 뺀다
    [peer] = payload["market_compare"]["peers"]
    assert (peer["relation"], peer["judge_in_sentence"]) == ("diverges", False)
    report = gen.canned_report(payload)
    assert report["summary"]["relative"] == (
        "같은 자동차 그룹의 기아는 2.40% 올랐고, 현대모비스는 2.40% 올랐습니다. 같은 그룹의 현대차는 보합이었습니다.")
    assert _compare_warnings(report, payload) == set()
    report["summary"]["relative"] = ("현대모비스는 코스피와는 다르게 움직였고, 같은 자동차 그룹의 기아는 2.40% 올랐습니다. "
                                     "같은 그룹의 현대차는 보합이었습니다.")
    assert _compare_warnings(report, payload) == {COMPARE_TARGET_RATE_MISSING}


def test_target_rate_in_next_sentence_is_found() -> None:
    payload = _payload(1.80, [0.00, 1.00])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = ("같은 자동차 그룹의 기아는 1.00% 올랐고 현대차는 보합이었습니다. "
                                     "현대모비스는 1.80% 올랐습니다.")
    assert _compare_warnings(report, payload) == set()


# 비교 종목 1~3개(홀수·짝수), 보합 포함, 엇갈림, 과반 예외가 모두 나오게 고른 등락률. 대상은 비교 종목과 같은 값도 넣는다.
GRID_PEER_RATES = (-1.50, -0.50, 0.00, 0.40, 1.20, 2.40)
GRID_TARGETS = (-2.00, -0.60, 0.00, 0.40, 1.00, 1.80, 2.40, 3.20)
GRID_KOSPI = (-1.00, 0.62, 3.09)


def test_canned_report_never_trips_its_own_compare_warnings() -> None:
    """정형 보고서는 verify 를 통과하고 비교 경고(COMPARE_WARNINGS)가 0건이어야 한다. 판정·문장 규칙을 바꿨을 때 정형 문장과
    검증 정규식이 어긋나면 여기서 걸린다."""
    seen: Counter = Counter()
    failures = []
    for n in (1, 2, 3):
        for peers in itertools.combinations_with_replacement(GRID_PEER_RATES, n):
            for target in GRID_TARGETS:
                for kospi_rate in GRID_KOSPI:
                    payload = _payload(target, list(peers), kospi_rate)
                    [peer] = payload["market_compare"]["peers"]
                    seen[peer["relation"]] += 1
                    seen["mixed"] += peer["mixed"]
                    seen["split"] += any(m["in_sentence"] is False for m in peer["members_used"])
                    seen["unjudged"] += peer["judge_in_sentence"] is False
                    seen["majority_follows"] += peer["relation"] == "follows" and min(peers) < 0 < max(peers)
                    report = gen.canned_report(payload)
                    status = verify(report, payload)
                    warned = sorted(w for w in check_warnings(report, payload) if code_of(w) in COMPARE_WARNINGS)
                    if status != ("passed", []) or warned:
                        failures.append((target, peers, kospi_rate, report["summary"]["relative"], status, warned))
    # 조합이 판정·문장 경우를 모두 덮는지
    for key in ("follows", "diverges", "opposite", "inconclusive", "mixed", "split", "unjudged", "majority_follows"):
        assert seen[key] > 0, key
    assert failures == [], f"{len(failures)}건: {failures[:5]}"


# --- 그룹 두 개에 속한 종목 (삼성생명: 보험 + 삼성전자 연동) -----------------------------------------------------------
# 그룹 A 는 보험(비교 종목 1~3개), 그룹 B 는 삼성전자 연동(지분으로 이어진 묶음) 또는 일반 그룹(1~2개). 두 그룹의 판정이
# 같거나 다르거나, 하나만·둘 다 엇갈리거나, 코스피 follows 앞 문장이 어느 그룹에 붙는지 섞인다. DB손해보험은 시험용 추가
# 종목이다(실제 보험 그룹은 삼성화재·메리츠금융지주).

TWO_TARGET = ("032830", "삼성생명")
TWO_A = ("보험", [("000810", "삼성화재"), ("138040", "메리츠금융지주"), ("005830", "DB손해보험")])
TWO_B_LINKED = ("삼성전자 연동", [("005930", "삼성전자"), ("028260", "삼성물산")])
TWO_B_PLAIN = ("금융지주", [("105560", "KB금융"), ("055550", "신한지주")])
TWO_PEER_RATES = (-1.50, 0.00, 0.40, 1.20, 2.40)
TWO_TARGETS = (-2.00, -0.60, 0.00, 0.40, 1.80, 3.20)
TWO_KOSPI = (-1.00, 0.62)


def _two_group_payload(target: float, peers_a: tuple, peers_b: tuple, kospi_rate: float, group_b: tuple) -> dict:
    code, name = TWO_TARGET
    (name_a, members_a), (name_b, members_b) = TWO_A, group_b
    members_a, members_b = members_a[:len(peers_a)], members_b[:len(peers_b)]
    groups = {name_a: {code: name, **dict(members_a)}, name_b: {code: name, **dict(members_b)}}
    stocks = [stock(code, 100, target)] + [stock(c, 100, r) for (c, _), r in zip(members_a + members_b, peers_a + peers_b)]
    ctx = build_market_context(code, DAY, kospi(kospi_rate), stocks, groups=groups,
                               stock_groups={code: (name_a, name_b)})
    compare = mc.to_input(ctx, groups=groups)
    excess = round(target - kospi_rate, 2)
    compare["kospi"] = {
        "stock_change_rate_pct": target, "kospi_change_rate_pct": kospi_rate, "excess_vs_kospi_pp": excess,
        "kospi_weight_pct": 0.7, "kospi_contribution_pp": 0.0, "kospi_ex_self_change_rate_pct": kospi_rate,
        "excess_vs_kospi_ex_self_pp": excess, "kospi_basis": "kospi",
        "kospi_relation": kospi_relation(excess, target, kospi_rate)}
    return _report_input(name, code, target, kospi_rate, compare)


def test_canned_report_with_two_groups_never_trips_its_own_compare_warnings() -> None:
    seen: Counter = Counter()
    failures = []
    for group_b in (TWO_B_LINKED, TWO_B_PLAIN):
        for n_a in (1, 2, 3):
            for peers_a in itertools.combinations_with_replacement(TWO_PEER_RATES, n_a):
                for n_b in (1, 2):
                    for peers_b in itertools.combinations_with_replacement(TWO_PEER_RATES, n_b):
                        for target in TWO_TARGETS:
                            for kospi_rate in TWO_KOSPI:
                                payload = _two_group_payload(target, peers_a, peers_b, kospi_rate, group_b)
                                a, b = payload["market_compare"]["peers"]
                                pair = (a["relation"], b["relation"])
                                seen["same" if pair[0] == pair[1] else "different"] += 1
                                seen[f"mixed{a['mixed'] + b['mixed']}"] += 1
                                seen["both_follows_kospi_follows"] += (
                                    pair == ("follows", "follows")
                                    and payload["market_compare"]["kospi"]["kospi_relation"] == "follows")
                                seen["one_unjudged"] += (a["judge_in_sentence"] is False) != (b["judge_in_sentence"] is False)
                                seen["mixed_and_follows"] += {a["mixed"], b["mixed"]} == {True, False} and "follows" in pair
                                report = gen.canned_report(payload)
                                status = verify(report, payload)
                                warned = sorted(w for w in check_warnings(report, payload) if code_of(w) in COMPARE_WARNINGS)
                                if status != ("passed", []) or warned:
                                    failures.append((group_b[0], target, peers_a, peers_b, kospi_rate,
                                                     report["summary"]["relative"], status, warned))
    for key in ("same", "different", "mixed0", "mixed1", "mixed2", "both_follows_kospi_follows", "one_unjudged",
                "mixed_and_follows"):
        assert seen[key] > 0, key
    assert failures == [], f"{len(failures)}건: {failures[:5]}"


# --- 부호 붙은 비교 종목 수치 (COMPARE_MEMBER_RATE), "섞여" 표현 (COMPARE_MIXED_NOT_STATED) --------------------------
# 팀 리뷰: 크기만 보고 부호를 안 봐서 "현대차(-2.16%)와 기아(+0.83%)" 처럼 방향을 반대로 써도 통과했다.
# 리뷰 예시 그룹 — 현대차 +2.16·기아 −0.83, 대상 현대모비스 +2.50.

@pytest.mark.parametrize("relative", [
    f"같은 자동차 그룹의 현대차(-2.16%)와 기아(+0.83%)는 {MIXED_TAIL}",  # 괄호 안, 둘 다 반대 (- 하이픈)
    f"같은 자동차 그룹의 현대차(−2.16%)와 기아(0.83%)는 {MIXED_TAIL}",  # 유니코드 마이너스, 현대차만 틀림
    f"같은 자동차 그룹의 현대차(+2.16%)와 기아(+0.83%)는 {MIXED_TAIL}",  # 기아만 틀림
    f"같은 자동차 그룹의 현대차는 -2.16%, 기아는 +0.83%로 {MIXED_TAIL}",  # 괄호 없이 부호만
])
def test_llm_signed_member_rate_with_wrong_direction_is_warned(relative) -> None:
    payload = _payload(2.50, [2.16, -0.83])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    warnings = [w for w in check_warnings(report, payload) if code_of(w) == COMPARE_MEMBER_RATE]
    assert len(warnings) == 1 and "부호가 입력 방향과 다르다" in warnings[0]


@pytest.mark.parametrize("relative", [
    f"같은 자동차 그룹의 현대차(+2.16%)와 기아(-0.83%)는 {MIXED_TAIL}",  # 맞는 부호 (- 하이픈)
    f"같은 자동차 그룹의 현대차(+2.16%)와 기아(−0.83%)는 {MIXED_TAIL}",  # 맞는 부호 (− 유니코드)
    f"같은 자동차 그룹의 현대차(2.16%)와 기아(0.83%)는 {MIXED_TAIL}",  # 부호도 방향 말도 없으면 크기만
    # 이 종목 수치는 바로 앞 이름이 이 종목이라 비교 종목 부호로 보지 않는다
    f"같은 자동차 그룹의 현대차(+2.16%)·기아(−0.83%)는 {MIXED_TAIL} 현대모비스는 +2.50% 올랐습니다.",
])
def test_llm_signed_member_rate_with_right_direction_is_not_warned(relative) -> None:
    payload = _payload(2.50, [2.16, -0.83])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert _compare_warnings(report, payload) == set()


@pytest.mark.parametrize(("range_text", "warned"), [
    ("0.35-0.80%", False),  # 숫자 뒤에 붙은 "-" 는 범위다. 부호로 읽으면 기아(+0.80)와 방향이 반대라 걸린다
    ("0.35, -0.80%", True),  # 쉼표 뒤의 "-" 는 부호다
])
def test_hyphen_after_number_is_a_range_not_a_sign(range_text, warned) -> None:
    payload = _payload(0.27, [0.35, 0.80, -1.37])  # 현대차 +0.35·기아 +0.80 은 문장에, 현대위아 −1.37 은 따로
    report = gen.canned_report(payload)
    report["summary"]["relative"] = (
        f"현대모비스는 코스피, 그리고 같은 자동차 그룹의 현대차·기아({range_text})와 비슷하게 움직여 시장 전체 흐름을 "
        "따라갔습니다. 같은 그룹의 현대위아는 1.37% 내렸습니다.")
    assert (COMPARE_MEMBER_RATE in _compare_warnings(report, payload)) is warned


@pytest.mark.parametrize("relative", [
    "같은 자동차 그룹의 현대차는 2.16% 올랐고 기아는 0.83% 내려, 오른 종목과 내린 종목이 섞여 그룹 흐름과 비교하기 어렵습니다.",
    ("같은 자동차 그룹의 현대차는 2.16% 올랐고 기아는 0.83% 내렸습니다. 오른 종목과 내린 종목이 섞인 그룹이라 그룹 흐름과 "
     "비교하기 어렵습니다."),
])
def test_mixed_stated_with_seokyeo_is_not_warned(relative) -> None:
    payload = _payload(2.50, [2.16, -0.83])
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert _compare_warnings(report, payload) == set()


# --- 대상 이름이 비교 종목 이름의 앞부분인 경우 (SK ⊂ SK스퀘어·SK하이닉스) ------------------------------------------
# 코드 리뷰: 대상 이름을 부분 문자열로 찾아, 대상 SK 가 "SK스퀘어" 안에서도 잡혔다. 그 뒤의 SK스퀘어 등락률을 SK 것으로 봐
# COMPARE_TARGET_RATE_MISSING 이 나지 않았고, 부호 검사도 "SK그룹" 안의 SK 를 대상으로 봐 비교 종목 부호를 건너뛰었다.

SK_GROUP = ("SK하이닉스 연동", [("000660", "SK하이닉스"), ("402340", "SK스퀘어")])


def _sk_payload() -> dict:
    """대상 SK +1.00, SK하이닉스 0.00·SK스퀘어 +1.00. 판정은 follows(중앙값 0.50)."""
    code, name = "034730", "SK"
    group, members = SK_GROUP
    groups = {group: {code: name, **dict(members)}}
    stocks = [stock(code, 100, 1.00), stock("000660", 100, 0.00), stock("402340", 100, 1.00)]
    ctx = build_market_context(code, DAY, kospi(KOSPI_RATE), stocks, groups=groups, stock_groups={code: (group,)})
    compare = mc.to_input(ctx, groups=groups)
    excess = round(1.00 - KOSPI_RATE, 2)
    compare["kospi"] = {
        "stock_change_rate_pct": 1.00, "kospi_change_rate_pct": KOSPI_RATE, "excess_vs_kospi_pp": excess,
        "kospi_weight_pct": 0.7, "kospi_contribution_pp": 0.0, "kospi_ex_self_change_rate_pct": KOSPI_RATE,
        "excess_vs_kospi_ex_self_pp": excess, "kospi_basis": "kospi",
        "kospi_relation": kospi_relation(excess, 1.00, KOSPI_RATE)}
    return _report_input(name, code, 1.00, KOSPI_RATE, compare)


@pytest.mark.parametrize(("relative", "missing"), [
    # SK 등락률을 빼고 SK스퀘어 수치만 — "SK스퀘어" 안의 SK 는 대상이 아니다
    ("SK하이닉스 지분으로 이어진 SK스퀘어는 1.00% 올랐습니다. SK하이닉스 지분으로 이어진 SK하이닉스는 보합이었습니다.", True),
    (("SK하이닉스 지분으로 이어진 SK스퀘어는 1.00% 올랐고, SK는 1.00% 올랐습니다. "
      "SK하이닉스 지분으로 이어진 SK하이닉스는 보합이었습니다."), False),
    ("SK하이닉스 지분으로 이어진 SK스퀘어는 1.00% 올랐고, SK(+1.00%)도 올랐습니다.", False),
])
def test_target_name_inside_member_name_is_not_the_target(relative, missing) -> None:
    payload = _sk_payload()
    [peer] = payload["market_compare"]["peers"]
    assert peer["relation"] == "follows" and peer["judge_in_sentence"] is True
    # verify 단위 시험: 판정하는 말을 빼는 그룹이라고 두고 대상 등락률 찾기만 본다(이 숫자로는 다시 판정해도 follows 라
    # 실제 입력에서는 true 다 — 대상과 비교 종목 등락률이 같으면 문장에 보이는 종목과의 차이가 0 이다)
    peer["judge_in_sentence"] = False
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert (COMPARE_TARGET_RATE_MISSING in _compare_warnings(report, payload)) is missing


@pytest.mark.parametrize(("relative", "warned"), [
    # "SK그룹" 안의 SK 를 대상으로 보면 -1.00% 를 대상 수치로 보고 건너뛴다. 앞 종목은 SK스퀘어(+1.00)다
    ("SK하이닉스 지분으로 이어진 SK스퀘어는 SK그룹 재편 기대 속에 -1.00%, SK하이닉스는 보합이었습니다.", True),
    ("SK하이닉스 지분으로 이어진 SK스퀘어는 SK그룹 재편 기대 속에 +1.00%, SK하이닉스는 보합이었습니다.", False),
    # 대상 SK 자신의 수치는 비교 종목 부호로 보지 않는다
    ("SK하이닉스 지분으로 이어진 SK스퀘어는 1.00% 올랐고, SK는 +1.00% 올랐습니다.", False),
])
def test_signed_rate_owner_is_found_by_whole_name(relative, warned) -> None:
    payload = _sk_payload()
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert (COMPARE_MEMBER_RATE in _compare_warnings(report, payload)) is warned


def _sk_square_payload() -> dict:
    """대상 SK스퀘어 +1.00, 비교 종목 SK +0.50 하나. SK하이닉스는 그날 시세가 없어 비교 종목에서 빠진다(members_excluded
    missing). 비교 종목에 SK 가 있고, 문장에는 비교 종목이 아닌 SK하이닉스가 나온다."""
    code, name, group = "402340", "SK스퀘어", "SK하이닉스 연동"
    groups = {group: {code: name, "000660": "SK하이닉스", "034730": "SK"}}
    stocks = [stock(code, 100, 1.00), stock("034730", 100, 0.50)]
    ctx = build_market_context(code, DAY, kospi(KOSPI_RATE), stocks, groups=groups, stock_groups={code: (group,)})
    compare = mc.to_input(ctx, groups=groups)
    excess = round(1.00 - KOSPI_RATE, 2)
    compare["kospi"] = {
        "stock_change_rate_pct": 1.00, "kospi_change_rate_pct": KOSPI_RATE, "excess_vs_kospi_pp": excess,
        "kospi_weight_pct": 0.7, "kospi_contribution_pp": 0.0, "kospi_ex_self_change_rate_pct": KOSPI_RATE,
        "excess_vs_kospi_ex_self_pp": excess, "kospi_basis": "kospi",
        "kospi_relation": kospi_relation(excess, 1.00, KOSPI_RATE)}
    payload = _report_input(name, code, 1.00, KOSPI_RATE, compare)
    [peer] = compare["peers"]
    assert [m["name"] for m in peer["members_used"]] == ["SK"]
    return payload


@pytest.mark.parametrize(("relative", "missing"), [
    # 이 종목 이름과 수치 사이의 "SK하이닉스" 안 SK 를 비교 종목 SK 로 보면 1.00% 를 SK 것으로 보고 건너뛴다
    ("SK스퀘어는 SK하이닉스 지분 가치가 오르며 1.00% 올랐고, SK하이닉스 지분으로 이어진 SK는 0.50% 올랐습니다.", False),
    # 이름과 수치 사이에 비교 종목 SK 가 단어로 끼면 그 수치는 SK 것이다
    ("SK스퀘어는 SK하이닉스 지분 가치가 오르며 올랐고, SK하이닉스 지분으로 이어진 SK는 0.50% 올랐습니다.", True),
])
def test_member_name_inside_other_name_is_not_the_member_for_target_rate(relative, missing) -> None:
    payload = _sk_square_payload()
    [peer] = payload["market_compare"]["peers"]
    assert peer["relation"] == "follows" and peer["judge_in_sentence"] is True
    # verify 단위 시험: 판정하는 말을 빼는 그룹이라고 두고 대상 등락률 찾기만 본다(test_target_name_inside_member_name_… 와 같은 방식)
    peer["judge_in_sentence"] = False
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert (COMPARE_TARGET_RATE_MISSING in _compare_warnings(report, payload)) is missing


@pytest.mark.parametrize(("relative", "warned"), [
    # 비교 종목 SK 가 나오지 않는 문장. "SK하이닉스" 안의 SK 로 비교 종목 문장이라고 보면 SK하이닉스 수치 3.20% 를
    # 입력에 없는 비교 종목 수치로 경고한다
    ("SK스퀘어는 1.00% 올랐고, SK하이닉스는 3.20% 올랐습니다. SK하이닉스 지분으로 이어진 SK는 0.50% 올랐습니다.", False),
    # 비교 종목 SK 를 쓴 문장의 입력에 없는 수치는 지금처럼 경고한다
    ("SK스퀘어는 1.00% 올랐고, SK하이닉스 지분으로 이어진 SK는 3.20% 올랐습니다.", True),
    # 조사가 겹치거나 "보다" 가 붙어도 비교 종목 이름이다
    ("SK스퀘어는 1.00% 올라, 3.20% 오른 SK보다 덜 올랐습니다.", True),
    ("SK스퀘어는 1.00% 올랐고, SK에서도 3.20% 를 말했습니다.", True),
])
def test_member_name_inside_other_name_is_not_the_member_for_member_rate(relative, warned) -> None:
    payload = _sk_square_payload()
    report = gen.canned_report(payload)
    report["summary"]["relative"] = relative
    assert (COMPARE_MEMBER_RATE in _compare_warnings(report, payload)) is warned
