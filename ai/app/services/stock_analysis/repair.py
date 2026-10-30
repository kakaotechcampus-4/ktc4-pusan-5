"""quote 검증에 떨어진 factor·background 항목을 한 번 고쳐 쓰게 한다.

검증기(verify.check_grounding)는 느슨하게 하지 않는다. 대신 검증 **전에** factor 와 background 항목마다
출처 quote 가 그 url 메시지 원문에 있는지 보고, 없으면 실패한 quote 와 원문 메시지를 주고 그 항목
하나만 다시 쓰게 한다. 다시 써도 원문에 없으면 그 항목을 빼고 events 에 dropped
(reason: quote_verify_fail) 로 남긴다. 그래서 quote 하나 때문에 보고서 전체가 failed 가 되지 않는다.

repair 는 **quote 만 고치는 단계**다. 고쳐 쓴 결과에서 받는 칸은 sources 뿐이고 나머지(event·detail·text·
stance·unconfirmed·links·watch)는 원래 값을 둔다. 고쳐 쓴 결과의 event(background 는 text)가 원래 문장과 한
글자라도 다르면 고친 것으로 받지 않고 그 항목을 뺀다(record.rejected = "event_changed"). 같은 뉴스 모음 메시지
안의 다른 항목으로 사건을 갈아 끼우고 strength 는 원래 값으로 남는 일이 있었다(2026-10-25, v6~v8 결과).

counter 는 등락 반대 방향 재료(하락일은 background.bullish, 상승일은 bearish)를 요약하는 칸이다. 그 칸 항목을
하나라도 빼거나 background 가 모두 비면 summary.counter 를 null 로 둔다 — counter 문장이 뺀 재료를 말하고 있을 수
있고, 그대로 두면 COUNTER_WITHOUT_BACKGROUND 로 failed 가 될 수도 있다. 다시 쓰지 않는다: counter 는 비워도 되는
칸이고 남은 재료의 상세는 background 에 그대로 있다. 기록에 counter_cleared 로 남긴다. 등락률을 모르면 칸을 가를 수
없어 background 가 모두 빌 때만 비운다.

factor 를 빼도 repair_quotes 는 summary 문장을 고치지 않는다. 뺀 factor 에 등락 층(move) link 가 있었으면
rewrite_summary("main_cause"), 상대 층(relative) link 가 있었으면 rewrite_summary("relative") 가 남은 근거만으로
그 칸을 한 번 다시 쓰게 한다. relative 의 첫 문장은 코스피·그룹 비교(입력 market_compare)라 근거를 빼도 지우지 않는다 —
다시 쓸 때 market_compare 를 함께 주고, 남은 상대 층 근거가 없어도 쓸 그룹 비교가 있으면 그 문장만 남게 다시 쓴다.
남은 근거도 쓸 그룹 비교도 없으면 LLM 을 부르지 않고 null 로 둔다(비워도 되는 칸).
다시 쓰지 못하면 러너가 MAIN_CAUSE_STALE·RELATIVE_STALE 경고를 남긴다.

비용 상한: factor 가 CAPS["factors"] 를, background 전체가 CAPS["background"] 를 넘은 보고서는 repair 하지 않는다
(repair_limit). 모델이 개수 상한을 어긴 보고서는 이미 형식이 어긋난 것이고, 넘친 항목마다 호출하면 비용이 상한 없이
는다. quote 가 틀린 항목은 그대로 남아 검증에서 실패하고, 러너가 REPAIR_SKIPPED_OVER_CAP 경고를 남긴다. 상한 안이면
repair 대상은 많아야 REPAIR_MAX_ITEMS(= 4 + 6)개다.
"""

import json
import logging
from typing import Any

from app.llm.client import LLMError, StreamInterrupted, complete, cost_detail
from app.services.stock_analysis.verify import (
    BACKGROUND_SLOTS,
    CAPS,
    QUOTE_NOT_IN_SOURCE,
    QUOTE_VERIFY_FAIL,
    _background_is_empty,
    _background_ref,
    _check_source,
    _factors,
    _links,
    _messages,
    _sources,
    layer_pct,
    normalize_report,
)

logger = logging.getLogger(__name__)

# 고쳐 쓰기 응답은 항목 하나라 짧다. 추론 모델이 생각에 예산을 쓰므로 넉넉히 둔다.
REPAIR_MAX_TOKENS = 8000
# 보고서 한 건에서 repair 대상이 될 수 있는 항목 수. 개수 상한(CAPS)을 지킨 보고서의 factor + background 전체다.
REPAIR_MAX_ITEMS = CAPS["factors"] + CAPS["background"]

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


def repair_limit(report: dict[str, Any]) -> dict[str, Any]:
    """래퍼 repair_limit 칸. hit 이면 repair 하지 않는다(factor 나 background 전체가 개수 상한을 넘었다)."""
    factors = report.get("factors")
    background = report.get("background")
    n_factors = len(factors) if isinstance(factors, list) else 0
    n_background = sum(len(v) for v in background.values() if isinstance(v, list)) if isinstance(background, dict) else 0
    return {"hit": n_factors > CAPS["factors"] or n_background > CAPS["background"], "factors": n_factors,
            "background": n_background, "max_items": REPAIR_MAX_ITEMS}


def counter_slot(payload: dict[str, Any]) -> str | None:
    """summary.counter 가 요약하는 background 칸. 등락 반대 방향이라 하락일 bullish, 상승일 bearish. 모르면 None."""
    change = layer_pct(payload, "move")
    if not change:
        return None
    return "bullish" if change < 0 else "bearish"


async def repair_quotes(
    report: dict[str, Any], payload: dict[str, Any], *, stream: bool, run_id: str = ""
) -> list[dict[str, Any]]:
    """report 를 제자리에서 고친다. 고친 항목마다 한 일을 돌려준다(래퍼 quote_repair 칸).

    한 항목에 한 번만 다시 묻는다. 호출 실패·응답을 못 연 경우도 다시 쓴 quote 가 틀린 것과
    같이 항목을 뺀다 — 근거가 검증되지 않은 채 화면에 나가는 것보다 낫다.
    repair_limit 이 hit 이면 아무것도 하지 않고 빈 목록이다(모듈 설명 「비용 상한」).
    """
    if repair_limit(report)["hit"]:
        return []
    messages = _messages(payload)
    records: list[dict[str, Any]] = []
    factor_drops: list[int] = []
    background_drops: list[tuple[str, int]] = []
    for kind, path, place, item in _targets(report)[:REPAIR_MAX_ITEMS]:
        failures = quote_failures(item, messages, path)
        if not failures:
            continue
        system, locked = _KINDS[kind]
        record: dict[str, Any] = {"kind": kind, "path": path}
        if kind == "factor":
            record.update(factor_index=place, event=item.get("event"), layers=_layers(item))
        else:
            record.update(slot=place[0], text=item.get("text"))
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
    if background_drops and isinstance(summary, dict) and isinstance(summary.get("counter"), str) \
            and summary["counter"].strip():
        slot = counter_slot(payload)
        emptied = _background_is_empty(report)
        hit = [r for r in records if r["kind"] == "background" and r["result"] == "dropped"
               and (emptied or r["slot"] == slot)]
        if hit:
            summary["counter"] = None
            for r in hit:
                r["counter_cleared"] = True
    return records


_SUMMARY_SYSTEM = """\
주가 변동 보고서의 summary.{field} 한 칸을 다시 씁니다. 이 칸은 {what}입니다.

보고서를 쓴 뒤 근거(factor) 일부가 출처 확인에 실패해 빠졌습니다(dropped). 지금 {field} 는 빠진
근거를 아직 말하고 있을 수 있습니다. **{basis}만으로** {field} 를 다시 쓰세요.

- {scope}에 없는 내용은 쓰지 않습니다. 빠진 근거의 내용은 한 마디도 남기지 않습니다.
- 최대 max_sentences 문장, 줄글입니다. {layer_name} link({layer}_link)의 strength 가 높은 것부터 씁니다.
  strength 가 insufficient 인 근거는 넣지 않습니다.
- {empty}
- 간접 근거(sources 의 match 가 모두 indirect)나 미확인(unconfirmed: true)에서 온 원인은
  추정·미확인임이 드러나게 씁니다("…가 부담이 됐을 수 있습니다").
- 지금 {field} 의 문장 중 남은 근거를 말하는 부분은 표현을 되도록 그대로 둡니다.
- 방향이 반대인 재료를 섞지 않습니다.
{extra}
출력은 JSON 객체 하나입니다. 첫 글자는 `{{`, 마지막 글자는 `}}` 입니다. 코드펜스·설명 금지.
{{"{field}": {shape}}}
"""

# relative 의 비교 문장 규칙. 프롬프트 3부 「비교 수치」와 4부 summary.relative 를 줄인 것이다.
_RELATIVE_COMPARE_RULES = """
**비교 문장 — market_compare.** 코스피·그룹과 비교한 수치입니다. 빠진 근거와 상관없는 문장이라 지우지 않습니다.

- 첫 문장은 코스피 판정(`kospi.kospi_relation`)과 그룹 판정(`peers[].relation`)을 함께 읽은 해석입니다. 지금 relative 에
  이 문장이 있으면 표현을 그대로 둡니다. 남은 근거가 하나도 없어도 이 문장은 남깁니다.

  | 코스피 · 그룹 | 첫 문장 |
  | --- | --- |
  | `follows` · `follows` | 코스피와 같은 그룹 모두와 비슷하게 움직여 시장 전체 흐름을 따라갔다 |
  | `diverges` · `follows` | 코스피와는 다르게 같은 그룹과 함께 움직였다. 방향이 다르면 "코스피는 올랐지만 …는 같은 … 그룹과 함께 내렸습니다" |
  | 어느 쪽이든 · `diverges` | 같은 그룹과 크게 달랐다. 이어서 이 종목만의 재료(남은 근거에 있을 때만) |
  | 어느 쪽이든 · `inconclusive` | 판정하는 말 없이 비교 종목의 등락률만 |

- 그룹 이름, 비교한 종목, 그룹 평균 등락률을 쓰고, 코스피는 수치 없이 말로만 씁니다. 초과분 숫자는 쓰지 않습니다.
  수치는 market_compare 에 있는 값만 씁니다. 직접 계산하지 않습니다.
- `kospi_basis` 가 `kospi_ex_self` 면 코스피 대신 "<종목명>을 뺀 코스피" 와 비교합니다. 코스피 판정이 `null` 이면 그룹 쪽만 씁니다.
- `members_used` 가 한 종목이면 "평균" 이라 하지 않고 그 종목 이름으로 씁니다. 이름에 "연동" 이 들어간 그룹은 지분으로 이어진
  종목 묶음입니다 — 같은 업종이라고 쓰지 않습니다.
- market_compare 가 `null` 이거나 `status` 가 `ok` 가 아니거나, `peers` 가 비었거나 `peers[].relation` 이 모두 `null` 이면
  비교 문장을 쓰지 않습니다.
- "판정하기 어렵"·"기준 시장"·"비교 종목이 하나뿐" 같은 안쪽 말은 쓰지 않습니다.
"""

MAIN_CAUSE_SYSTEM = _SUMMARY_SYSTEM.format(
    field="main_cause", what="오늘 등락의 원인 요약", basis="남은 근거(remaining_factors)", scope="남은 근거",
    layer_name="등락 층", layer="move",
    empty='partial 이상인 근거가 하나도 없으면 그 사실을 적습니다. 남은 근거가 하나도 없으면\n'
          '  "제공된 메시지에서 확인된 원인은 없습니다." 로 적습니다.',
    extra="", shape='"..."')
RELATIVE_SYSTEM = _SUMMARY_SYSTEM.format(
    field="relative", what="상대 층 — 코스피·그룹 판정을 함께 읽은 해석과 다른 대형주와 달랐던 이유",
    basis="남은 근거(remaining_factors)와 비교 수치(market_compare)", scope="남은 근거와 비교 수치(market_compare)",
    layer_name="상대 층", layer="relative",
    empty="partial 이상인 근거가 없으면 비교 문장만 씁니다. 쓸 근거도 비교 문장도 없으면 null 입니다.",
    extra=_RELATIVE_COMPARE_RULES, shape='"..." 또는 null')

# 칸마다 (그 칸이 요약하는 층, 판정 칸, 시스템 프롬프트). relative 는 비워도 되는 칸이다(남은 근거도 쓸 그룹 비교도 없으면 null).
_SUMMARY_FIELDS = {"main_cause": ("move", "verdict", MAIN_CAUSE_SYSTEM),
                   "relative": ("relative", "relative_verdict", RELATIVE_SYSTEM)}
# relative 칸의 문장 수 상한(프롬프트 4부 summary 표).
RELATIVE_MAX_SENTENCES = 3
# 이 status 일 때만 비교 문장을 쓴다(프롬프트 3부 「비교 수치」).
COMPARE_OK = "ok"


def has_group_compare(market_compare: Any) -> bool:
    """relative 의 비교 문장을 쓸 수 있는가. status 가 ok 이고 판정(relation)이 있는 그룹이 하나라도 있어야 한다.
    코스피 판정만 있는 날은 relative 에 비교 문장을 쓰지 않는다(코스피 판정 문장은 move 에 있다)."""
    if not isinstance(market_compare, dict) or market_compare.get("status") != COMPARE_OK:
        return False
    return any(isinstance(p, dict) and p.get("relation") is not None for p in market_compare.get("peers") or [])


def _summary_user(report: dict[str, Any], field: str, dropped: list[dict[str, Any]], sentences: int,
                  remaining: list[dict[str, Any]], market_compare: dict[str, Any] | None) -> str:
    _, verdict_key, _ = _SUMMARY_FIELDS[field]
    body = {verdict_key: report.get(verdict_key), "max_sentences": sentences,
            field: report["summary"][field], "dropped": [r.get("event") for r in dropped],
            "remaining_factors": remaining}
    if field == "relative":
        body["market_compare"] = market_compare
    return json.dumps(body, ensure_ascii=False, indent=2)


def _remaining(report: dict[str, Any], layer: str) -> list[dict[str, Any]]:
    out = []
    for f in _factors(normalize_report(report)):
        link = next((x for x in _links(f) if x.get("layer") == layer), None)
        if link is not None:
            out.append({"event": f.get("event"), "detail": f.get("detail"),
                        "stance": f.get("stance"), "unconfirmed": f.get("unconfirmed"),
                        "source_matches": [s.get("match") for s in _sources(f)],
                        f"{layer}_link": {"note": link.get("note"), "strength": link.get("strength")}})
    return out


async def rewrite_summary(
    report: dict[str, Any], records: list[dict[str, Any]], field: str, *, stream: bool, run_id: str = "",
    sentences: int = 3, market_compare: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """repair_quotes 가 그 칸의 층(main_cause 는 move, relative 는 relative) link 를 가진 factor 를 뺐으면 그 칸을
    한 번 다시 쓰게 한다. market_compare 는 모델에 보낸 입력 칸이고 relative 를 다시 쓸 때만 쓴다.

    report 를 제자리에서 고친다. 할 일이 없으면 None, 있으면 기록(래퍼 main_cause_rewrite·relative_rewrite 칸)을
    돌려준다. result 는 rewritten | cleared(relative 를 null 로 둠) | failed. relative 는 남은 상대 층 근거도 쓸 그룹
    비교도 없으면 LLM 없이 cleared, 남은 근거가 없어도 그룹 비교가 있으면 비교 문장만 남게 다시 쓴다. 다시 쓴 결과가
    null 이어도 cleared 다. failed 면 칸은 그대로이고 러너가 MAIN_CAUSE_STALE·RELATIVE_STALE 경고를 단다. relative 가
    이미 null 이면 할 일이 없다.
    """
    layer, _, system = _SUMMARY_FIELDS[field]
    dropped = [r for r in records if r.get("result") == "dropped" and layer in (r.get("layers") or [])]
    if not dropped:
        return None
    summary = report.get("summary")
    if field == "relative" and isinstance(summary, dict) and summary.get("relative") is None:
        return None
    record: dict[str, Any] = {"result": "failed", "dropped": [r.get("event") for r in dropped],
                              "before": None, "after": None, "usage": None, "cost": 0.0, "error": None}
    if not isinstance(summary, dict) or not isinstance(summary.get(field), str):
        record["error"] = f"summary.{field} 가 없다"
        return record
    record["before"] = summary[field]
    remaining = _remaining(report, layer)
    if field == "relative" and not remaining and not has_group_compare(market_compare):
        summary["relative"] = None
        record.update(result="cleared")
        return record
    try:
        text, usage = await complete(
            system, _summary_user(report, field, dropped, sentences, remaining, market_compare),
            max_tokens=REPAIR_MAX_TOKENS, stream=stream)
    except (LLMError, StreamInterrupted) as exc:
        logger.warning("%s: %s 다시 쓰기 실패: %s", run_id, field, exc)
        record["error"] = str(exc)
        return record
    record["usage"] = usage
    record["cost"], _ = cost_detail(usage)
    from app.services.stock_analysis.generate import extract_json  # 순환 import 를 피한다

    _, parsed, _ = extract_json(text)
    after = parsed.get(field) if isinstance(parsed, dict) else None
    # relative 는 쓸 근거도 비교 문장도 없다고 null 로 답할 수 있다(비워도 되는 칸)
    if field == "relative" and isinstance(parsed, dict) and field in parsed and after is None:
        summary[field] = None
        record.update(result="cleared")
        return record
    if not isinstance(after, str) or not after.strip():
        record["error"] = f"다시 쓴 응답에서 {field} 를 읽지 못함"
        return record
    summary[field] = after
    record.update(result="rewritten", after=after)
    return record


async def rewrite_main_cause(
    report: dict[str, Any], records: list[dict[str, Any]], *, stream: bool, run_id: str = "", sentences: int = 3
) -> dict[str, Any] | None:
    """rewrite_summary(field="main_cause")."""
    return await rewrite_summary(report, records, "main_cause", stream=stream, run_id=run_id, sentences=sentences)


__all__ = ["BACKGROUND_REPAIR_SYSTEM", "MAIN_CAUSE_SYSTEM", "RELATIVE_MAX_SENTENCES", "RELATIVE_SYSTEM", "REPAIR_MAX_ITEMS",
           "REPAIR_SYSTEM", "counter_slot", "has_group_compare", "quote_failures", "repair_limit", "repair_quotes",
           "rewrite_main_cause", "rewrite_summary"]
