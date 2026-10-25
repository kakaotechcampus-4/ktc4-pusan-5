"""모델 출력 뒤 러너가 정하는 칸. 모델이 판단할 필요가 없는 값은 러너가 다시 계산하거나 직접 넣는다.

    recompute_strength   link strength 를 5단계 정의(출처의 입력 match·상한)로 다시 정한다
    recompute_verdicts   층별 판정을 검증 판정표(verify._check_verdict_tables)로 다시 정한다
    fix_main_cause       common_move·market_led 날 main_cause 의 앞뒤 고정 문장을 붙인다

같은 입력과 같은 사건 선택이면 strength·판정·고정 문장이 회차마다 같아야 하는데, 모델에 맡기면 같은 출처를
두고도 partial·sufficient 가 갈리고 고정 문장을 빠뜨렸다(2026-10-25, runner_v12). 모델이 적은 값은 래퍼에
남기고(strength_recomputed·verdict_recomputed·main_cause_fixed) 경고 STRENGTH_MISMATCH 는 모델 값으로 센다.

quote 고쳐 쓰기(repair)로 factor 가 빠질 수 있어 그 뒤, 검증 앞에서 부른다(collectors.stock_analysis).
정형 보고서(skipped_llm)는 부르지 않는다 — 러너가 이미 정해서 낸 보고서다.
"""

import re
from typing import Any

from app.services.stock_analysis.verify import (
    CAPPED_SIZE_FIT,
    LAYERS,
    VERDICT_KEYS,
    _factors,
    _has_direct_source,
    _links,
    _messages,
    common_move,
    layer_pct,
    market_led,
    move_strength_cap,
    normalize_report,
)

# 고정 문장. 오른·내린 은 change_pct 부호로 정한다(common_move·market_led 날은 대형주 중간값과 부호가 같다).
HEAD_SENTENCE = "대형주 전반이 함께 {verb} 날이었습니다."
TAIL_SENTENCE = "이 종목만의 원인은 따로 확인되지 않았습니다."
# 모델이 같은 문장을 이미 썼으면 지우고 러너 문장 하나만 남긴다. 방향을 틀리게 쓴 것도 같은 문장으로 본다.
_HEAD_RE = re.compile(r"대형주 전반이 함께 (?:오른|내린) 날이었습니다\.?")
_TAIL_RE = re.compile(re.escape(TAIL_SENTENCE[:-1]) + r"\.?")


def defined_strength(factor: dict[str, Any], layer: str, matches: dict[Any, Any], move_capped: bool) -> str:
    """5단계 정의의 strength. 출처에 입력 match=direct 가 하나라도 있으면 sufficient, 없으면 partial.
    미확인(unconfirmed) factor 와, move_strength_cap 이 partial 인 날의 등락 층은 partial 까지다."""
    capped = factor.get("unconfirmed") is True or (layer == "move" and move_capped)
    return CAPPED_SIZE_FIT if _has_direct_source(factor, matches) and not capped else "partial"


def recompute_strength(report: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    """link 마다 strength 를 정의대로 고친다. report 를 제자리에서 고치고 [{factor, layer, model, final}] 을 돌려준다.

    모든 link 를 적는다(바뀌지 않은 것도) — 모델이 적은 값을 래퍼에서 다시 볼 수 있게 한다. 건드리지 않는 link:
    direction_match 가 false(counter 로 갈 재료라 검증이 실패로 잡는다), strength 가 insufficient(출처로 정할 수 없는
    "거의 닿지 않음" 판단), layer 나 strength 가 목록 밖(스키마 실패).
    """
    matches = {m.get("url"): m.get("match") for m in _messages(payload)}
    move_capped = move_strength_cap(payload) == "partial"
    out: list[dict[str, Any]] = []
    for i, f in enumerate(_factors(report)):
        for link in _links(f):
            layer, model = link.get("layer"), link.get("strength")
            final = model
            if layer in LAYERS and model in (CAPPED_SIZE_FIT, "partial") and link.get("direction_match") is not False:
                final = defined_strength(f, layer, matches, move_capped)
                link["strength"] = final
            out.append({"factor": i, "layer": layer, "model": model, "final": final})
    return out


def layer_verdict(report: dict[str, Any], layer: str) -> str:
    """검증 판정표(_check_verdict_tables)의 층별 판정. 그 층 link 에 sufficient 가 있으면 explained, link 가 있으면
    partially_explained, 없으면 no_clear_cause.

    judge_layers 가 false 인 층(check_judge_layers)은 link 가 없으면 이 표로도 no_clear_cause 다. link 가 남아 있으면
    두 규칙을 함께 맞추는 판정이 없어 표를 따른다 — 검증은 FLAT_*_VERDICT·FLAT_*_FACTORS 로 실패한다.
    """
    strengths = [x.get("strength") for f in _factors(report) for x in _links(f) if x.get("layer") == layer]
    if CAPPED_SIZE_FIT in strengths:
        return "explained"
    return "partially_explained" if strengths else "no_clear_cause"


def recompute_verdicts(report: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    """verdict·relative_verdict 를 layer_verdict 로 고친다. [{key, model, final}] 을 돌려준다."""
    out: list[dict[str, Any]] = []
    for layer, key in VERDICT_KEYS.items():
        model, final = report.get(key), layer_verdict(report, layer)
        report[key] = final
        out.append({"key": key, "model": model, "final": final})
    return out


def fix_main_cause(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    """common_move·market_led 날 main_cause 앞에 HEAD_SENTENCE 를, common_move 날은 끝에 TAIL_SENTENCE 를 붙인다.

    모델은 그 사이 내용만 쓴다(프롬프트 4부). 모델이 같은 문장을 써 두었으면 지우고 붙여 한 번만 나오게 한다.
    해당하는 날이 아니면 None, 붙였으면 {before, after}.
    """
    common, led = common_move(payload) is True, market_led(payload) is True
    change = layer_pct(payload, "move")
    summary = report.get("summary")
    if not (common or led) or not change or not isinstance(summary, dict):
        return None
    before = summary.get("main_cause") if isinstance(summary.get("main_cause"), str) else ""
    middle = _HEAD_RE.sub("", before)
    if common:
        middle = _TAIL_RE.sub("", middle)
    parts = [HEAD_SENTENCE.format(verb="오른" if change > 0 else "내린"), " ".join(middle.split())]
    if common:
        parts.append(TAIL_SENTENCE)
    after = " ".join(p for p in parts if p)
    summary["main_cause"] = after
    return {"before": before, "after": after}


def finalize(report: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """세 가지를 차례로 한다. strength 를 먼저 고쳐야 판정이 고친 strength 를 본다. 래퍼에 넣을 칸을 돌려준다.
    이전 형식 factor(layer·size_fit)는 links 형식으로 펴서 고친다 — 그대로 두면 link 가 없어 판정을 잘못 낸다."""
    if isinstance(report.get("factors"), list):
        report["factors"] = normalize_report(report)["factors"]
    return {"strength_recomputed": recompute_strength(report, payload),
            "verdict_recomputed": recompute_verdicts(report, payload),
            "main_cause_fixed": fix_main_cause(report, payload)}


__all__ = ["HEAD_SENTENCE", "TAIL_SENTENCE", "defined_strength", "finalize", "fix_main_cause", "layer_verdict",
           "recompute_strength", "recompute_verdicts"]
