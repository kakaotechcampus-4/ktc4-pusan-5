"""quote 검증에 떨어진 factor·background 항목을 한 번 고쳐 쓰게 한다.

검증기(verify.check_grounding)는 느슨하게 하지 않는다. 대신 검증 **전에** factor 와 background 항목마다
출처 quote 가 그 url 메시지 원문에 있는지 보고, 없으면 실패한 quote 와 원문 메시지를 주고 그 항목
하나만 다시 쓰게 한다. 다시 써도 원문에 없으면 그 항목을 빼고 events 에 dropped
(reason: quote_verify_fail) 로 남긴다. 그래서 quote 하나 때문에 보고서 전체가 failed 가 되지 않는다.

repair 는 **quote 만 고치는 단계**다. 고쳐 쓴 결과에서 받는 칸은 sources 뿐이고 나머지(event·detail·text·
stance·unconfirmed·links·watch)는 원래 값을 둔다. 고쳐 쓴 결과의 event(background 는 text)가 원래 문장과 한
글자라도 다르면 고친 것으로 받지 않고 그 항목을 뺀다(record.rejected = "event_changed"). 같은 뉴스 모음 메시지
안의 다른 항목으로 사건을 갈아 끼우고 strength 는 원래 값으로 남는 일이 있었다(2026-10-25, v6~v8 결과).

background 항목을 빼서 background 가 모두 비면 summary.counter 를 null 로 둔다. counter 는 background 에
있는 재료만 요약하는 칸이라(COUNTER_WITHOUT_BACKGROUND), 그대로 두면 뺀 재료를 말하는 문장이 남고
보고서가 failed 가 된다. 기록에 counter_cleared 로 남긴다.

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
    BACKGROUND_SLOTS,
    QUOTE_NOT_IN_SOURCE,
    QUOTE_VERIFY_FAIL,
    _background_is_empty,
    _background_ref,
    _check_source,
    _factors,
    _links,
    _messages,
    _sources,
    normalize_report,
)

logger = logging.getLogger(__name__)

# 고쳐 쓰기 응답은 항목 하나라 짧다. 추론 모델이 생각에 예산을 쓰므로 넉넉히 둔다.
REPAIR_MAX_TOKENS = 8000

_QUOTE_RULES = """\
**quote 만 고칩니다.** {fields} 은 입력의 문장을 글자 그대로 다시 적고, event·detail·links·strength 는
바꾸지 않습니다. 같은 메시지 안의 다른 소식으로 바꾸지 마세요.
아래 원문 메시지에서 그 사건을 뒷받침하는 구절을 **글자 그대로 복사한** 40자 이내 quote 로 바꾸세요. 띄어쓰기
말고는 한 글자도 바꾸면 안 됩니다. 그 사건을 뒷받침하는 구절을 찾을 수 없으면 sources 를 빈 배열로 둡니다.
원문에 "인공지능(AI)" 처럼 말 뒤에 괄호 속 영문 약어가 붙어 있으면 quote 에는 "인공지능(AI)",
"인공지능", "AI" 중 어느 꼴로 옮겨도 됩니다.

출력은 JSON 객체 하나입니다. 첫 글자는 `{{`, 마지막 글자는 `}}` 입니다. 코드펜스·설명 금지.
{shape}
sources 의 url 은 아래 원문 메시지 url 중에서만 고릅니다.
"""
_SOURCE_SHAPE = ('{"channel": "", "url": "", "datetime_kst": "", "quote": "", '
                 '"match": "direct|indirect", "is_market_recap": false}')

REPAIR_SYSTEM = """\
주가 변동 보고서의 근거(factor) 하나를 고칩니다.

이 factor 의 출처 quote 가 그 url 메시지 원문에 글자 그대로 들어 있지 않아 검증에서 떨어졌습니다.
""" + _QUOTE_RULES.format(fields="event",
                          shape='{"event": "<입력 factor 의 event 그대로>", "sources": [' + _SOURCE_SHAPE + "]}")

BACKGROUND_REPAIR_SYSTEM = """\
주가 변동 보고서의 참고 재료(background) 항목 하나를 고칩니다.

이 항목의 출처 quote 가 그 url 메시지 원문에 글자 그대로 들어 있지 않아 검증에서 떨어졌습니다.
""" + _QUOTE_RULES.format(fields="text",
                          shape='{"text": "<입력 항목의 text 그대로>", "sources": [' + _SOURCE_SHAPE + "]}")

# 종류마다 (시스템 프롬프트, 바뀌면 안 되는 칸). 고쳐 쓴 응답에서는 sources 만 받는다.
_KINDS = {"factor": (REPAIR_SYSTEM, "event"),
          "background": (BACKGROUND_REPAIR_SYSTEM, "text")}


def quote_failures(item: dict[str, Any], messages: list[dict[str, Any]], path: str) -> list[str]:
    """출처 중 quote 가 원문에 없는 것. 문제 문자열은 verify 와 같은 형식이다."""
    out: list[str] = []
    for j, s in enumerate(_sources(item)):
        _check_source(s, f"{path}.sources[{j}]", messages, out)
    return [p for p in out if p.startswith(QUOTE_NOT_IN_SOURCE)]


def _repair_user(kind: str, item: dict[str, Any], failures: list[str],
                 messages: list[dict[str, Any]]) -> str:
    urls = {s.get("url") for s in _sources(item)}
    scope = [{"channel": m.get("channel"), "url": m.get("url"), "datetime_kst": m.get("datetime_kst"),
              "match": m.get("match"), "text": m.get("text")}
             for m in messages if m.get("url") in urls]
    return json.dumps({kind: item, "failed_quotes": failures, "messages": scope},
                      ensure_ascii=False, indent=2)


def _parse_rewrite(text: str) -> dict[str, Any] | None:
    from app.services.stock_analysis.generate import extract_json  # 순환 import 를 피한다

    _, parsed, _ = extract_json(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("sources"), list) or not parsed["sources"]:
        return None
    return parsed


def _layers(factor: dict[str, Any]) -> list[Any]:
    """factor 가 link 를 단 층. 이전 형식(layer 문자열)도 편다."""
    normalized = normalize_report({"factors": [factor]})
    return [x.get("layer") for f in _factors(normalized) for x in _links(f)]


def _events(report: dict[str, Any]) -> list[Any] | None:
    return report.get("events") if isinstance(report.get("events"), list) else None


def _drop(report: dict[str, Any], index: int) -> None:
    """factors[index] 를 빼고 events 를 맞춘다. 그 factor 를 가리키던 사건은 dropped 로 바꾼다."""
    factor = report["factors"].pop(index)
    events = _events(report)
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


def _drop_background(report: dict[str, Any], slot: str, index: int) -> None:
    """background[slot][index] 를 빼고 events 를 맞춘다.

    그 항목을 가리키던 사건(placed: background, background: {slot, index})은 dropped 로 바꾸고, 같은 칸
    뒤 항목을 가리키던 사건의 index 를 하나씩 당긴다. 가리키는 사건이 없으면(예전 형식) 사건을 하나 더한다.
    """
    item = report["background"][slot].pop(index)
    events = _events(report)
    if events is None:
        return
    hit = next((e for e in events if isinstance(e, dict) and e.get("placed") == "background"
                and _background_ref(e) == (slot, index)), None)
    if hit is None:
        hit = {"event": item.get("text", ""), "issue_ids": [], "dup_channels": None}
        events.append(hit)
    hit.pop("background", None)
    hit.update(placed="dropped", reason=QUOTE_VERIFY_FAIL)
    for e in events:
        ref = _background_ref(e) if isinstance(e, dict) and e.get("placed") == "background" else None
        if ref is not None and ref[0] == slot and ref[1] > index:
            e["background"] = {**e["background"], "index": ref[1] - 1}


def _targets(report: dict[str, Any]) -> list[tuple[str, str, Any, dict[str, Any]]]:
    """(종류, 경로, 자리, 항목). 자리는 factor 면 순번, background 면 (칸, 순번)."""
    out: list[tuple[str, str, Any, dict[str, Any]]] = []
    factors = report.get("factors")
    for i, f in enumerate(factors if isinstance(factors, list) else []):
        if isinstance(f, dict):
            out.append(("factor", f"factors[{i}]", i, f))
    background = report.get("background")
    if isinstance(background, dict):
        for slot in BACKGROUND_SLOTS:
            items = background.get(slot)
            for i, item in enumerate(items if isinstance(items, list) else []):
                if isinstance(item, dict):
                    out.append(("background", f"background.{slot}[{i}]", (slot, i), item))
    return out


async def repair_quotes(
    report: dict[str, Any], payload: dict[str, Any], *, stream: bool, run_id: str = ""
) -> list[dict[str, Any]]:
    """report 를 제자리에서 고친다. 고친 항목마다 한 일을 돌려준다(래퍼 quote_repair 칸).

    한 항목에 한 번만 다시 묻는다. 호출 실패·응답을 못 연 경우도 다시 쓴 quote 가 틀린 것과
    같이 항목을 뺀다 — 근거가 검증되지 않은 채 화면에 나가는 것보다 낫다.
    """
    messages = _messages(payload)
    records: list[dict[str, Any]] = []
    factor_drops: list[int] = []
    background_drops: list[tuple[str, int]] = []
    for kind, path, place, item in _targets(report):
        failures = quote_failures(item, messages, path)
        if not failures:
            continue
        system, locked = _KINDS[kind]
        record: dict[str, Any] = {"kind": kind, "path": path}
        if kind == "factor":
            record.update(factor_index=place, event=item.get("event"), layers=_layers(item))
        else:
            record["text"] = item.get("text")
        record.update(failed=failures, usage=None, cost=0.0, error=None)
        rewritten = None
        try:
            text, usage = await complete(system, _repair_user(kind, item, failures, messages),
                                         max_tokens=REPAIR_MAX_TOKENS, stream=stream)
            record["usage"] = usage
            record["cost"], _ = cost_detail(usage)
            rewritten = _parse_rewrite(text)
            if rewritten is None:
                record["error"] = f"고쳐 쓴 응답을 {kind} 로 열지 못함"
        except (LLMError, StreamInterrupted) as exc:
            logger.warning("%s: %s quote 고쳐 쓰기 실패: %s", run_id, path, exc)
            record["error"] = str(exc)
        if rewritten is not None and rewritten.get(locked) != item.get(locked):
            # 사건을 바꿔 썼다. quote 만 고치는 단계라 받지 않고 뺀다.
            record["rejected"] = "event_changed"
            record["rewritten_" + locked] = rewritten.get(locked)
            rewritten = None
        if rewritten is not None:
            candidate = {**item, "sources": rewritten["sources"]}
            still = quote_failures(candidate, messages, path)
            record["retry_failed"] = still
            if not still:
                if kind == "factor":
                    report["factors"][place] = candidate
                else:
                    report["background"][place[0]][place[1]] = candidate
                record["result"] = "fixed"
                record["quotes"] = [s.get("quote") for s in _sources(candidate)]
                records.append(record)
                continue
        record["result"] = "dropped"
        record["summary_may_mention"] = True
        (factor_drops if kind == "factor" else background_drops).append(place)
        records.append(record)
    for i in sorted(factor_drops, reverse=True):
        _drop(report, i)
    for slot, i in sorted(background_drops, reverse=True):
        _drop_background(report, slot, i)
    summary = report.get("summary")
    if background_drops and _background_is_empty(report) and isinstance(summary, dict) \
            and isinstance(summary.get("counter"), str) and summary["counter"].strip():
        summary["counter"] = None
        for r in records:
            if r["kind"] == "background" and r["result"] == "dropped":
                r["counter_cleared"] = True
    return records


MAIN_CAUSE_SYSTEM = """\
주가 변동 보고서의 summary.main_cause 한 칸을 다시 씁니다.

보고서를 쓴 뒤 근거(factor) 일부가 출처 확인에 실패해 빠졌습니다(dropped). 지금 main_cause 는 빠진
근거를 아직 말하고 있을 수 있습니다. **남은 근거(remaining_factors)만으로** main_cause 를 다시 쓰세요.

- 남은 근거에 없는 내용은 쓰지 않습니다. 빠진 근거의 내용은 한 마디도 남기지 않습니다.
- 최대 main_cause_sentences 문장, 줄글입니다. 등락 층 link(move_link)의 strength 가 높은 것부터 씁니다.
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


def _main_cause_user(report: dict[str, Any], dropped: list[dict[str, Any]], sentences: int = 3) -> str:
    remaining = []
    for f in _factors(normalize_report(report)):
        move = next((x for x in _links(f) if x.get("layer") == "move"), None)
        if move is None:
            continue
        remaining.append({"event": f.get("event"), "detail": f.get("detail"),
                          "stance": f.get("stance"), "unconfirmed": f.get("unconfirmed"),
                          "source_matches": [s.get("match") for s in _sources(f)],
                          "move_link": {"note": move.get("note"), "strength": move.get("strength")}})
    return json.dumps({"verdict": report.get("verdict"), "main_cause_sentences": sentences,
                       "main_cause": report["summary"]["main_cause"],
                       "dropped": [r.get("event") for r in dropped],
                       "remaining_factors": remaining}, ensure_ascii=False, indent=2)


async def rewrite_main_cause(
    report: dict[str, Any], records: list[dict[str, Any]], *, stream: bool, run_id: str = "", sentences: int = 3
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
        text, usage = await complete(MAIN_CAUSE_SYSTEM, _main_cause_user(report, dropped, sentences),
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


__all__ = ["BACKGROUND_REPAIR_SYSTEM", "MAIN_CAUSE_SYSTEM", "REPAIR_SYSTEM", "quote_failures", "repair_quotes", "rewrite_main_cause"]
