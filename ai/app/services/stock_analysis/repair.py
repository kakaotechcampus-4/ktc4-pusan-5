"""quote 검증에 떨어진 factor 를 한 번 고쳐 쓰게 한다.

검증기(verify.check_grounding)는 느슨하게 하지 않는다. 대신 검증 **전에** factor 마다 출처
quote 가 그 url 메시지 원문에 있는지 보고, 없으면 실패한 quote 와 원문 메시지를 주고 그 factor
하나만 다시 쓰게 한다. 다시 써도 원문에 없으면 factor 에서 빼고 events 에 dropped
(reason: quote_verify_fail) 로 남긴다.

고쳐 쓴 결과에서 받는 칸은 event·detail·sources 뿐이다. stance·unconfirmed·links 는 원래 값을
둔다 — quote 를 고치다가 판정(strength·층)이 바뀌면 verdict 표 검증과 어긋난다.

factor 를 빼도 repair_quotes 는 summary 문장을 고치지 않는다. 뺀 factor 에 등락 층(move) link 가
있었으면 rewrite_main_cause 가 남은 근거만으로 summary.main_cause 를 한 번 다시 쓰게 한다. 다시 쓰지
못하면 러너가 MAIN_CAUSE_STALE 경고를 남긴다. relative·counter 등 다른 summary 칸은 고치지 않고
기록(quote_repair[].summary_may_mention)에만 남긴다.
"""

import json
import logging
from typing import Any

from app.llm.client import LLMError, StreamInterrupted, complete, cost_detail
from app.services.stock_analysis.verify import (
    QUOTE_NOT_IN_SOURCE,
    QUOTE_VERIFY_FAIL,
    _check_source,
    _factors,
    _links,
    _messages,
    _sources,
    normalize_report,
)

logger = logging.getLogger(__name__)

# 고쳐 쓰기 응답은 factor 하나라 짧다. 추론 모델이 생각에 예산을 쓰므로 넉넉히 둔다.
REPAIR_MAX_TOKENS = 8000

REPAIR_SYSTEM = """\
주가 변동 보고서의 근거(factor) 하나를 고칩니다.

이 factor 의 출처 quote 가 그 url 메시지 원문에 글자 그대로 들어 있지 않아 검증에서 떨어졌습니다.
아래 원문 메시지에서 **글자 그대로 복사한** 40자 이내 quote 로 바꾸세요. 띄어쓰기 말고는 한 글자도
바꾸면 안 됩니다. 원문에서 그 사건을 뒷받침하는 문장을 찾을 수 없으면 event·detail 을 원문에 있는
내용으로 좁혀 쓰세요. 원문에 없는 내용을 새로 만들지 않습니다.
괄호 속 영문 약어(예: "(AI)")는 빼고 옮겨도 됩니다. 원문의 말을 약어로 바꿔 쓰면 안 됩니다
(원문 "인공지능(AI) 산업" → O "인공지능 산업", X "AI 산업").

출력은 JSON 객체 하나입니다. 첫 글자는 `{`, 마지막 글자는 `}` 입니다. 코드펜스·설명 금지.
{"event": "...", "detail": "...", "sources": [{"channel": "", "url": "", "datetime_kst": "", "quote": "", "match": "direct|indirect", "is_market_recap": false}]}
sources 의 url 은 아래 원문 메시지 url 중에서만 고릅니다.
"""


def quote_failures(factor: dict[str, Any], messages: list[dict[str, Any]], path: str) -> list[str]:
    """factor 출처 중 quote 가 원문에 없는 것. 문제 문자열은 verify 와 같은 형식이다."""
    out: list[str] = []
    for j, s in enumerate(_sources(factor)):
        _check_source(s, f"{path}.sources[{j}]", messages, out)
    return [p for p in out if p.startswith(QUOTE_NOT_IN_SOURCE)]


def _repair_user(factor: dict[str, Any], failures: list[str], messages: list[dict[str, Any]]) -> str:
    urls = {s.get("url") for s in _sources(factor)}
    scope = [{"channel": m.get("channel"), "url": m.get("url"), "datetime_kst": m.get("datetime_kst"),
              "match": m.get("match"), "text": m.get("text")}
             for m in messages if m.get("url") in urls]
    return json.dumps({"factor": factor, "failed_quotes": failures, "messages": scope},
                      ensure_ascii=False, indent=2)


def _parse_factor(text: str) -> dict[str, Any] | None:
    from app.services.stock_analysis.generate import extract_json  # 순환 import 를 피한다

    _, parsed, _ = extract_json(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sources"), list) or not parsed["sources"]:
        return None
    return parsed


def _layers(factor: dict[str, Any]) -> list[Any]:
    """factor 가 link 를 단 층. 이전 형식(layer 문자열)도 편다."""
    normalized = normalize_report({"factors": [factor]})
    return [x.get("layer") for f in _factors(normalized) for x in _links(f)]


def _drop(report: dict[str, Any], index: int) -> None:
    """factors[index] 를 빼고 events 를 맞춘다. 그 factor 를 가리키던 사건은 dropped 로 바꾼다."""
    factor = report["factors"].pop(index)
    events = report.get("events") if isinstance(report.get("events"), list) else None
    if events is None:
        return
    hit = next((e for e in events if isinstance(e, dict)
                and e.get("placed") == "factors" and e.get("factor") == index), None)
    if hit is None:
        hit = {"event": factor.get("event", ""), "issue_ids": [], "dup_channels": None}
        events.append(hit)
    hit.pop("factor", None)
    hit.update(placed="dropped", reason=QUOTE_VERIFY_FAIL)
    for e in events:
        if isinstance(e, dict) and isinstance(e.get("factor"), int) and e["factor"] > index:
            e["factor"] -= 1


async def repair_quotes(
    report: dict[str, Any], payload: dict[str, Any], *, stream: bool, run_id: str = ""
) -> list[dict[str, Any]]:
    """report 를 제자리에서 고친다. factor 마다 한 일을 돌려준다(래퍼 quote_repair 칸).

    한 factor 에 한 번만 다시 묻는다. 호출 실패·응답을 못 연 경우도 다시 쓴 quote 가 틀린 것과
    같이 factor 를 뺀다 — 근거가 검증되지 않은 채 화면에 나가는 것보다 낫다.
    """
    factors = report.get("factors")
    if not isinstance(factors, list):
        return []
    messages = _messages(payload)
    records: list[dict[str, Any]] = []
    drops: list[int] = []
    for i, factor in enumerate(factors):
        if not isinstance(factor, dict):
            continue
        failures = quote_failures(factor, messages, f"factors[{i}]")
        if not failures:
            continue
        record: dict[str, Any] = {"factor_index": i, "event": factor.get("event"),
                                  "layers": _layers(factor),
                                  "failed": failures, "usage": None, "cost": 0.0, "error": None}
        rewritten = None
        try:
            text, usage = await complete(REPAIR_SYSTEM, _repair_user(factor, failures, messages),
                                         max_tokens=REPAIR_MAX_TOKENS, stream=stream)
            record["usage"] = usage
            record["cost"], _ = cost_detail(usage)
            rewritten = _parse_factor(text)
            if rewritten is None:
                record["error"] = "고쳐 쓴 응답을 factor 로 열지 못함"
        except (LLMError, StreamInterrupted) as exc:
            logger.warning("%s: factors[%d] quote 고쳐 쓰기 실패: %s", run_id, i, exc)
            record["error"] = str(exc)
        if rewritten is not None:
            candidate = {**factor, "event": rewritten.get("event", factor.get("event")),
                         "detail": rewritten.get("detail", factor.get("detail")),
                         "sources": rewritten["sources"]}
            still = quote_failures(candidate, messages, f"factors[{i}]")
            record["retry_failed"] = still
            if not still:
                factors[i] = candidate
                record["result"] = "fixed"
                record["quotes"] = [s.get("quote") for s in _sources(candidate)]
                records.append(record)
                continue
        record["result"] = "dropped"
        record["summary_may_mention"] = True
        drops.append(i)
        records.append(record)
    for i in sorted(drops, reverse=True):
        _drop(report, i)
    return records


MAIN_CAUSE_SYSTEM = """\
주가 변동 보고서의 summary.main_cause 한 칸을 다시 씁니다.

보고서를 쓴 뒤 근거(factor) 일부가 출처 확인에 실패해 빠졌습니다(dropped). 지금 main_cause 는 빠진
근거를 아직 말하고 있을 수 있습니다. **남은 근거(remaining_factors)만으로** main_cause 를 다시 쓰세요.

- 남은 근거에 없는 내용은 쓰지 않습니다. 빠진 근거의 내용은 한 마디도 남기지 않습니다.
- 최대 3문장, 줄글입니다. 등락 층 link(move_link)의 strength 가 높은 것부터 씁니다.
  strength 가 insufficient 인 근거는 넣지 않습니다.
- partial 이상인 근거가 하나도 없으면 그 사실을 적습니다. 남은 근거가 하나도 없으면
  "제공된 메시지에서 확인된 원인은 없습니다." 로 적습니다.
- 간접 근거(sources 의 match 가 모두 indirect)나 미확인(unconfirmed: true)에서 온 원인은
  추정·미확인임이 드러나게 씁니다("…가 부담이 됐을 수 있습니다").
- 지금 main_cause 의 문장 중 남은 근거를 말하는 부분은 표현을 되도록 그대로 둡니다.
- 방향이 반대인 재료를 섞지 않습니다.

출력은 JSON 객체 하나입니다. 첫 글자는 `{`, 마지막 글자는 `}` 입니다. 코드펜스·설명 금지.
{"main_cause": "..."}
"""


def _main_cause_user(report: dict[str, Any], dropped: list[dict[str, Any]]) -> str:
    remaining = []
    for f in _factors(normalize_report(report)):
        move = next((x for x in _links(f) if x.get("layer") == "move"), None)
        if move is None:
            continue
        remaining.append({"event": f.get("event"), "detail": f.get("detail"),
                          "stance": f.get("stance"), "unconfirmed": f.get("unconfirmed"),
                          "source_matches": [s.get("match") for s in _sources(f)],
                          "move_link": {"note": move.get("note"), "strength": move.get("strength")}})
    return json.dumps({"verdict": report.get("verdict"),
                       "main_cause": report["summary"]["main_cause"],
                       "dropped": [r.get("event") for r in dropped],
                       "remaining_factors": remaining}, ensure_ascii=False, indent=2)


async def rewrite_main_cause(
    report: dict[str, Any], records: list[dict[str, Any]], *, stream: bool, run_id: str = ""
) -> dict[str, Any] | None:
    """repair_quotes 가 등락 층 link 를 가진 factor 를 뺐으면 main_cause 를 한 번 다시 쓰게 한다.

    report 를 제자리에서 고친다. 할 일이 없으면 None, 있으면 기록(래퍼 main_cause_rewrite 칸)을
    돌려준다. result 가 rewritten 이 아니면 main_cause 는 그대로이고 러너가 MAIN_CAUSE_STALE 을 단다.
    """
    dropped = [r for r in records if r.get("result") == "dropped" and "move" in (r.get("layers") or [])]
    if not dropped:
        return None
    record: dict[str, Any] = {"result": "failed", "dropped": [r.get("event") for r in dropped],
                              "before": None, "after": None, "usage": None, "cost": 0.0, "error": None}
    summary = report.get("summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("main_cause"), str):
        record["error"] = "summary.main_cause 가 없다"
        return record
    record["before"] = summary["main_cause"]
    try:
        text, usage = await complete(MAIN_CAUSE_SYSTEM, _main_cause_user(report, dropped),
                                     max_tokens=REPAIR_MAX_TOKENS, stream=stream)
    except (LLMError, StreamInterrupted) as exc:
        logger.warning("%s: main_cause 다시 쓰기 실패: %s", run_id, exc)
        record["error"] = str(exc)
        return record
    record["usage"] = usage
    record["cost"], _ = cost_detail(usage)
    from app.services.stock_analysis.generate import extract_json  # 순환 import 를 피한다

    _, parsed, _ = extract_json(text)
    after = parsed.get("main_cause") if isinstance(parsed, dict) else None
    if not isinstance(after, str) or not after.strip():
        record["error"] = "다시 쓴 응답에서 main_cause 를 읽지 못함"
        return record
    summary["main_cause"] = after
    record.update(result="rewritten", after=after)
    return record


__all__ = ["MAIN_CAUSE_SYSTEM", "REPAIR_SYSTEM", "quote_failures", "repair_quotes", "rewrite_main_cause"]
