"""러너가 정하는 칸(finalize): strength·판정 재계산과 main_cause 고정 문장."""

import pytest

from app.services.stock_analysis.finalize import (
    finalize,
    fix_main_cause,
    recompute_strength,
    recompute_verdicts,
)
from app.services.stock_analysis.verify import check_warnings

DIRECT, INDIRECT = "https://t.me/a/1", "https://t.me/a/2"


def payload(code="999999", change=-1.5, peer=-1.4, excess=-0.1):
    return {"code": code, "stock": "테스트", "change_pct": change,
            "market": {"peer_median_pct": peer, "excess_pct": excess},
            "messages": [{"url": DIRECT, "match": "direct", "kind": "news", "text": "가"},
                         {"url": INDIRECT, "match": "indirect", "kind": "news", "text": "나"}]}


def factor(urls, *links, unconfirmed=False):
    return {"event": "e", "stance": "bearish", "unconfirmed": unconfirmed,
            "sources": [{"url": u, "quote": "q"} for u in urls],
            "links": [{"layer": layer, "strength": s, "direction_match": d} for layer, s, d in links]}


def report(factors, main_cause="원인입니다.", verdict="explained", relative_verdict="no_clear_cause"):
    return {"verdict": verdict, "relative_verdict": relative_verdict, "factors": factors,
            "summary": {"main_cause": main_cause}}


def test_strength_follows_direct_source_and_records_model_value():
    # 큰 등락(-3.0)·대형주 몫 작음(-0.5) — 상한 없음
    p = payload(change=-3.0, peer=-0.5, excess=-2.5)
    r = report([factor([INDIRECT], ("move", "sufficient", True)),
                factor([INDIRECT, DIRECT], ("move", "partial", True), ("relative", "partial", True)),
                factor([DIRECT], ("move", "sufficient", True), unconfirmed=True)])
    rec = recompute_strength(r, p)
    assert [(x["factor"], x["layer"], x["model"], x["final"]) for x in rec] == [
        (0, "move", "sufficient", "partial"), (1, "move", "partial", "sufficient"),
        (1, "relative", "partial", "sufficient"), (2, "move", "sufficient", "partial")]
    assert [x["strength"] for f in r["factors"] for x in f["links"]] == ["partial", "sufficient", "sufficient", "partial"]


def test_move_cap_limits_only_move_layer():
    # -3.0 중 -2.0 이 대형주 몫 → move_strength_cap partial. 상대 층(excess -1.5)은 상한 없음
    r = report([factor([DIRECT], ("move", "sufficient", True), ("relative", "sufficient", True))])
    rec = recompute_strength(r, payload(change=-3.0, peer=-2.0, excess=-1.5))
    assert [x["final"] for x in rec] == ["partial", "sufficient"]


def test_insufficient_and_wrong_direction_links_are_left_alone():
    r = report([factor([DIRECT], ("move", "insufficient", True)), factor([DIRECT], ("move", "partial", False))])
    rec = recompute_strength(r, payload(change=-3.0, peer=-0.5, excess=-2.5))
    assert [(x["model"], x["final"]) for x in rec] == [("insufficient", "insufficient"), ("partial", "partial")]


@pytest.mark.parametrize("strengths, expected", [
    (["partial", "sufficient"], "explained"),
    (["partial"], "partially_explained"),
    ([], "no_clear_cause"),
])
def test_verdict_follows_table(strengths, expected):
    r = report([factor([DIRECT], ("move", s, True)) for s in strengths], verdict="partially_explained")
    rec = recompute_verdicts(r, payload())
    assert r["verdict"] == expected and r["relative_verdict"] == "no_clear_cause"
    assert rec[0] == {"key": "verdict", "model": "partially_explained", "final": expected}


def test_common_move_day_gets_head_and_tail_once():
    r = report([], main_cause="대형주 전반이 함께 내린 날이었습니다. 금리 우려가 시장을 눌렀습니다. "
                              "이 종목만의 원인은 따로 확인되지 않았습니다.")
    fixed = fix_main_cause(r, payload())
    assert r["summary"]["main_cause"] == ("대형주 전반이 함께 내린 날이었습니다. 금리 우려가 시장을 눌렀습니다. "
                                          "이 종목만의 원인은 따로 확인되지 않았습니다.")
    assert fixed["before"].startswith("대형주 전반이")


def test_common_move_day_with_empty_middle():
    r = report([], main_cause="")
    fix_main_cause(r, payload(change=1.5, peer=1.4, excess=0.1))
    assert r["summary"]["main_cause"] == "대형주 전반이 함께 오른 날이었습니다. 이 종목만의 원인은 따로 확인되지 않았습니다."


def test_market_led_day_gets_head_only():
    # 삼성전자(유니버스 비중 0.40)는 시장을 움직이는 종목 — common_move 대신 market_led
    r = report([], main_cause="반도체 업황 우려가 부담이 됐을 수 있습니다.")
    fix_main_cause(r, payload(code="005930"))
    assert r["summary"]["main_cause"] == "대형주 전반이 함께 내린 날이었습니다. 반도체 업황 우려가 부담이 됐을 수 있습니다."


def test_other_days_are_untouched():
    r = report([], main_cause="원인입니다.")
    assert fix_main_cause(r, payload(change=-3.0, peer=-0.5, excess=-2.5)) is None
    assert r["summary"]["main_cause"] == "원인입니다."


def test_finalize_normalizes_legacy_factor_and_strength_warning_uses_model_value():
    p = payload(change=-3.0, peer=-0.5, excess=-2.5)
    legacy = {"claim": "e", "layer": "move", "size_fit": "partial", "direction_match": True, "stance": "bearish",
              "unconfirmed": False, "sources": [{"url": DIRECT, "quote": "q"}]}
    r = report([legacy], verdict="partially_explained")
    out = finalize(r, p)
    assert r["factors"][0]["links"][0]["strength"] == "sufficient" and r["verdict"] == "explained"
    # 고친 뒤 보고서로 보면 어긋남이 없지만, 모델 값으로 센다
    assert not [w for w in check_warnings(r, p) if w.startswith("STRENGTH_MISMATCH")]
    assert [w.split(":")[0] for w in check_warnings(r, p, model_strength=out["strength_recomputed"])
            if w.startswith("STRENGTH_MISMATCH")] == ["STRENGTH_MISMATCH"]
