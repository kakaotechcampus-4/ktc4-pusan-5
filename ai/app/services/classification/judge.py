"""④ (사건, 후보 종목)마다 해당 여부 판정 (CLASSIFICATION_DB_DRAFT 4-8).

자료 하나에 한 번 부른다. 후보가 있는 사건만 보낸다. 후보가 하나도 없으면 부르지 않는다.

    DIRECT            이 사건이 이 종목에 직접 해당한다
    INDIRECT_CONTEXT  이 종목의 업황·경쟁·거래 관계 배경이다
    NOT_APPLICABLE    후보였지만 이 종목과 관계없다 (같은 산업이지만 다른 제품 등)
    UNKNOWN           주어진 정보로 판단할 수 없다

판정 입력에는 후보의 산업 연결(경로·경유 회사·단계·역할)과 걸린 관계(종류·방향·산업·note)를 넣는다.
세부 산업 정보가 없으면 LLM 이 회사 사업을 짐작하게 되므로 이 정보가 판정의 근거다.

**저장 전 보정.** LLM 출력 하나가 CHECK 에 걸려 회차 전체가 롤백되지 않게 코드가 고치고 건수를 남긴다.

    direct_allowed = false 인데 DIRECT   → INDIRECT_CONTEXT    direct_lowered
    후보인데 판정 없음                    → UNKNOWN             missing_filled
    후보 밖 종목·판정하지 않은 사건        → 버림                outside_dropped
    허용 밖 판정 값                       → UNKNOWN             invalid_label
    같은 (사건, 종목)에 판정 둘 이상       → 처음 것만            duplicate_dropped

JSON 으로 열리지 않거나 사건 번호를 알아볼 수 없으면 보정하지 않고 JudgeParseError → 회차 failed.

**관계 후보 나눠 보내기(CLASSIFICATION_RELATION_JUDGE=jev).** 관계 경로 후보는 Jev 질문으로 판정하고
(judge_relation.py) 이 LLM 호출에는 회사·산업 경로 후보만 넣는다. 둘 중 하나라도 실패하면 회차 failed.
기본값 luna 는 지금처럼 호출 하나가 모든 후보를 판정한다.
"""

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field

from app.core.config import settings
from app.llm import jev
from app.services.classification import llm
from app.services.classification.basis import Basis
from app.services.classification.candidates import Candidate
from app.services.classification.events import Event, strip_fence
from app.services.classification.judge_relation import judge_relations
from app.services.classification.link import EntityLink

PROMPT_NAME = "classification_judge"
LABELS = ("DIRECT", "INDIRECT_CONTEXT", "NOT_APPLICABLE", "UNKNOWN")
FIX_KEYS = ("direct_lowered", "missing_filled", "outside_dropped", "invalid_label",
            "duplicate_dropped")

EXPOSURE_TEXT = {"own": "직접 영위", "subsidiary": "비상장 자회사", "stake": "상장사 지분"}
STAGE_TEXT = {"operating": "영위 중", "planned": "진출 예정"}
ROLE_TEXT = {
    "supplier": "{via}의 공급사", "customer": "{via}의 고객사", "competitor": "{via}의 경쟁사",
    "owner": "{via}의 지분을 가진 회사", "owned": "{via}가 지분을 가진 회사",
}


class JudgeParseError(ValueError):
    """판정 응답 형식이 깨졌다. 이 회차는 실패로 남긴다."""


@dataclass(frozen=True)
class Judgment:
    event_order: int
    stock_code: str
    label: str
    reason: str | None


@dataclass
class Judging:
    call: llm.StepCall | None  # 후보가 없으면 부르지 않는다
    judgments: dict[tuple[int, str], Judgment] = field(default_factory=dict)
    fixes: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIX_KEYS, 0))
    error: str | None = None
    relation_call: llm.StepCall | None = None  # 관계 후보를 Jev 로 판정했을 때만(judge_relation.py)


def _industry_line(basis: Basis, link) -> str:
    text = f"{basis.industries[link.industry_code].name}({EXPOSURE_TEXT[link.exposure]}"
    if link.via_company:
        text += f" {link.via_company}"
    if link.stage == "planned":
        text += f", {STAGE_TEXT['planned']}"
    if link.supply_role:
        text += f", 역할 {link.supply_role}"
    return text + ")"


def _relation_line(basis: Basis, ref: dict) -> str:
    text = ROLE_TEXT[ref["candidate_is"]].format(via=basis.display_name(ref["via"]))
    if ref.get("industry"):
        text += f" — {basis.industries[ref['industry']].name}"
    if ref.get("note"):
        text += f" — {ref['note']}"
    return text


def candidate_block(candidate: Candidate, basis: Basis) -> str:
    stock = basis.stocks[candidate.stock_code]
    cap = "DIRECT 가능" if candidate.direct_allowed else "최대 INDIRECT_CONTEXT"
    lines = [f"  - {stock.code} {stock.name} [{cap}]"]
    if candidate.path == "company":
        why = "기사에 직접 언급됨"
        if candidate.via_subsidiaries:
            why += " (자회사 " + "·".join(candidate.via_subsidiaries) + " 로 언급)"
    elif candidate.path == "industry":
        why = "산업 경로: " + _industry_line(basis, candidate.link)
    else:
        origin = candidate.via_stock_code or candidate.via_external_code
        why = f"관계 경로: 기사에 언급된 {basis.display_name(origin)}와의 관계"
    lines.append(f"      후보가 된 이유: {why}")
    lines.append("      회사 사업: " + ", ".join(_industry_line(basis, link)
                                             for link in basis.links_of(stock.code)))
    for ref in candidate.relation_refs:
        lines.append(f"      관계: {_relation_line(basis, ref)}")
    return "\n".join(lines)


def _link_text(link: EntityLink, basis: Basis) -> str:
    if link.stock_code:
        target = f"종목 {basis.stocks[link.stock_code].name}"
        if link.via_subsidiary:
            target += f"(자회사 {link.via_subsidiary})"
    elif link.external_code:
        target = f"외부 기업 {basis.externals[link.external_code].name}"
        if link.via_subsidiary:
            target += f"(자회사 {link.via_subsidiary})"
    else:
        target = f"산업 {basis.industries[link.industry_code].name}"
    return f"{link.mention} → {target}"


def build_judge_message(title: str, sentences: list[str],
                        items: list[tuple[Event, list[EntityLink], list[Candidate]]],
                        basis: Basis) -> str:
    parts = [f"[제목] {title.strip()}", "", "[본문]",
             *(f"[{i}] {s}" for i, s in enumerate(sentences, start=1)), "", "# 판정할 사건"]
    for event, links, candidates in items:
        parts.append(f"\n[사건 {event.order_index}] scope={event.scope} · role={event.role} · "
                     f"tense={event.tense}")
        if event.context_indices:
            parts.append("  문맥 문장: " + ", ".join(map(str, event.context_indices)))
        parts.append("  근거 문장: " + ", ".join(map(str, event.sentence_indices)))
        if links:
            parts.append("  기사 속 표기: " + " / ".join(_link_text(link, basis) for link in links))
        parts.append("  후보:")
        parts += [candidate_block(candidate, basis) for candidate in candidates]
    return "\n".join(parts)


def parse_judgments(text: str, candidates: dict[int, list[Candidate]]) -> Judging:
    """응답 → 보정한 판정. candidates 는 판정에 보낸 사건 순서 → 후보."""
    try:
        data = json.loads(strip_fence(text))
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"JSON 이 아니다: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("judgments"), list):
        raise JudgeParseError("최상위에 judgments 배열이 없다")

    allowed = {(order, c.stock_code): c for order, cands in candidates.items() for c in cands}
    result = Judging(call=None)
    fixes = Counter()
    for item in data["judgments"]:
        if not isinstance(item, dict):
            raise JudgeParseError("판정이 객체가 아니다")
        order = item.get("event")
        if not isinstance(order, int) or isinstance(order, bool):
            raise JudgeParseError(f"사건 번호를 알아볼 수 없다: {order!r}")
        key = (order, str(item.get("stock", "")).strip())
        candidate = allowed.get(key)
        if candidate is None:
            fixes["outside_dropped"] += 1
            continue
        if key in result.judgments:
            fixes["duplicate_dropped"] += 1
            continue
        label, reason = item.get("label"), item.get("reason")
        reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
        if label not in LABELS:
            fixes["invalid_label"] += 1
            reason = _fixed(f"허용 밖 판정 값 {label!r}", reason)
            label = "UNKNOWN"
        if label == "DIRECT" and not candidate.direct_allowed:
            fixes["direct_lowered"] += 1
            reason = _fixed("DIRECT 불가 후보", reason)
            label = "INDIRECT_CONTEXT"
        result.judgments[key] = Judgment(order, key[1], label, reason)
    for key in allowed:
        if key not in result.judgments:
            fixes["missing_filled"] += 1
            result.judgments[key] = Judgment(key[0], key[1], "UNKNOWN", "[보정: 판정 누락]")
    result.fixes.update(fixes)
    return result


def _fixed(what: str, reason: str | None) -> str:
    return f"[보정: {what}] {reason or ''}".rstrip()


async def judge(title: str, sentences: list[str],
                items: list[tuple[Event, list[EntityLink], list[Candidate]]], basis: Basis,
                *, model: str | None = None) -> Judging:
    items = [item for item in items if item[2]]
    if not items:
        return Judging(call=None)
    if settings.classification_relation_judge != "jev":
        return await _judge_with_llm(title, sentences, items, basis, model)

    # 관계 경로 후보는 Jev 로, 나머지(회사·산업)는 LLM 판정 호출로 나눠 보낸다. 둘은 서로 기다리지 않는다
    jev.endpoint()  # 설정이 빠졌으면 자료마다 실패로 남기지 않고 여기서 멈춘다
    split = {kind: [(e, links, [c for c in cands if (c.path == "relation") == (kind == "relation")])
                    for e, links, cands in items] for kind in ("llm", "relation")}
    split = {kind: [item for item in part if item[2]] for kind, part in split.items()}
    llm_part, relation_part = await asyncio.gather(
        _judge_with_llm(title, sentences, split["llm"], basis, model) if split["llm"] else _none(),
        judge_relations(title, sentences, split["relation"], basis) if split["relation"] else _none(),
    )
    result = llm_part or Judging(call=None)
    if relation_part is not None:
        relation_call, decided, missing, error = relation_part
        result.relation_call = relation_call
        if error and not result.error:
            result.error = error
        for (order, stock), (label, reason) in decided.items():
            result.judgments[(order, stock)] = Judgment(order, stock, label, reason)
        result.fixes["missing_filled"] += missing
    return result


async def _none() -> None:
    return None


async def _judge_with_llm(title: str, sentences: list[str],
                          items: list[tuple[Event, list[EntityLink], list[Candidate]]], basis: Basis,
                          model: str | None) -> Judging:
    call = await llm.call("judge", PROMPT_NAME, build_judge_message(title, sentences, items, basis),
                          model=model)
    if not call.ok:
        return Judging(call=call, error=call.error)
    try:
        result = parse_judgments(call.raw_response or "", {e.order_index: c for e, _, c in items})
    except JudgeParseError as exc:
        return Judging(call=call, error=llm.parse_failure(call, str(exc)))
    result.call = call
    return result
