"""같은 사건 묶기 (docs/CLASSIFICATION_SAME_EVENT.md). 분류가 끝난 사건을 묶는다.

**후보.** 코드가 먼저 좁힌다. 묶음 대표와 scope 가 같고, 연결 코드나 연결되지 않은 표기가 겹치고,
공개 시각 차이가 48시간 안이어야 한다. 대표와만 견준다 — 구성원끼리 이으면 A~B, B~C 가 비슷할 때
다른 사건인 A 와 C 까지 합쳐진다. 같은 회차의 사건이 대표인 묶음은 후보가 아니다.

**응답 검사.** LLM 출력 하나 때문에 자료 전체를 버리지 않게 코드가 고치고 건수를 남긴다.

    후보 밖 묶음 번호          → 새 묶음      outside_new
    보내지 않은 사건 번호      → 버림         unknown_dropped
    같은 답을 두 번            → 하나만       duplicate_dropped
    한 사건에 서로 다른 답     → 묶지 않음    conflict_left
    응답에 없는 사건           → 묶지 않음    missing_left

묶지 않은 사건은 다음 실행에서 다시 본다. JSON 으로 열리지 않거나 번호를 알아볼 수 없으면 고치지 않고
SameEventParseError → 그 자료는 묶지 않고 응답 원문과 오류를 남긴다.

**문장 복원.** 사건은 문장 번호만 저장하므로 문장은 원문을 다시 나눠 얻는다. 원문이 지워졌거나 분류할 때와
달라졌으면 번호가 맞는다고 할 수 없다. 대표가 그렇다면 그 묶음을 후보에서 빼고(representative_unreadable),
새 자료가 그렇다면 LLM 을 부르지 않고 그 자료를 묶지 않은 채로 둔다.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.services.classification import llm, splitter
from app.services.classification.basis import normalize_mention
from app.services.classification.events import strip_fence

PROMPT_NAME = "classification_same_event"
CANDIDATE_WINDOW = timedelta(hours=48)
FIX_KEYS = ("outside_new", "unknown_dropped", "duplicate_dropped", "conflict_left", "missing_left",
            "representative_unreadable")


class SameEventParseError(ValueError):
    """응답 형식이 깨졌다. 이 자료는 묶지 않은 채로 둔다."""


@dataclass(frozen=True)
class ClusterEvent:
    """묶기에 필요한 사건 정보. 묶을 사건과 묶음 대표가 같은 모양이다."""

    event_id: int
    run_id: int
    card_id: int
    order_index: int
    scope: str
    available_at: datetime
    codes: frozenset[str]  # 연결 코드. entity_code 값
    mentions: frozenset[str]  # 연결되지 않은 표기. unlinked_mentions 값
    sentence_indices: tuple[int, ...]
    context_indices: tuple[int, ...]
    splitter_version: str  # 이 사건을 뽑은 회차의 값. 문장 복원에 쓴다
    input_sha256: str


@dataclass(frozen=True)
class EventText:
    context: tuple[str, ...]
    sentences: tuple[str, ...]


@dataclass
class Assignments:
    # 사건 순서 → 묶음 번호. None 이면 새 묶음. 없는 사건은 묶지 않은 채로 둔다
    clusters: dict[int, int | None] = field(default_factory=dict)
    fixes: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIX_KEYS, 0))


@dataclass
class Clustering(Assignments):
    """자료 하나의 묶기 결과. 호출이 실패했거나 문장을 복원하지 못하면 clusters 가 비어 있다."""

    asked: set[int] = field(default_factory=set)  # LLM 에 보낸 사건 순서
    call: llm.StepCall | None = None  # 후보가 없어 부르지 않았으면 None
    error: str | None = None


def entity_code(stock_code: str | None, industry_code: str | None,
                external_code: str | None) -> str:
    """종목·산업·외부 기업의 코드가 우연히 같아도 다른 대상으로 보게 종류를 붙인다."""
    if stock_code:
        return f"stock:{stock_code}"
    if industry_code:
        return f"industry:{industry_code}"
    return f"external:{external_code}"


def unlinked_mentions(mentions: list[str], linked: list[str]) -> frozenset[str]:
    """사건의 표기 중 어디에도 연결되지 않은 것(정규화한 값)."""
    linked_keys = {normalize_mention(mention) for mention in linked}
    return frozenset(normalize_mention(mention) for mention in mentions) - linked_keys


def is_candidate(event: ClusterEvent, representative: ClusterEvent) -> bool:
    return (
        event.run_id != representative.run_id
        and event.scope == representative.scope
        and abs(event.available_at - representative.available_at) <= CANDIDATE_WINDOW
        and bool(event.codes & representative.codes or event.mentions & representative.mentions)
    )


def candidates_for(events: list[ClusterEvent],
                   representatives: dict[int, ClusterEvent]) -> dict[int, list[int]]:
    """사건 순서 → 후보 묶음 번호. 후보가 없는 사건은 빈 목록이다."""
    return {
        event.order_index: [cluster_id for cluster_id, representative in representatives.items()
                            if is_candidate(event, representative)]
        for event in events
    }


def event_text(event: ClusterEvent, body: str | None) -> EventText | None:
    """사건의 문장을 원문에서 되찾는다. 원문이 분류할 때와 다르면 None."""
    if not body or hashlib.sha256(body.encode("utf-8")).hexdigest() != event.input_sha256:
        return None
    sentences = splitter.split(body, event.splitter_version)
    if max((*event.context_indices, *event.sentence_indices)) > len(sentences):
        return None
    return EventText(context=tuple(sentences[i - 1] for i in event.context_indices),
                     sentences=tuple(sentences[i - 1] for i in event.sentence_indices))


def _text_lines(text: EventText) -> list[str]:
    context = [f"  문맥: {' '.join(text.context)}"] if text.context else []
    return [*context, f"  문장: {' '.join(text.sentences)}"]


def build_message(events: list[tuple[ClusterEvent, EventText]], asked: dict[int, list[int]],
                  representatives: dict[int, EventText]) -> str:
    parts = ["# 새 자료의 사건"]
    for event, text in events:
        parts += ["", f"[사건 {event.order_index}]", *_text_lines(text),
                  "  후보 묶음: " + ", ".join(map(str, asked[event.order_index]))]
    parts += ["", "# 후보 묶음의 대표 사건"]
    for cluster_id, text in sorted(representatives.items()):
        parts += ["", f"[묶음 {cluster_id}]", *_text_lines(text)]
    return "\n".join(parts)


async def assign_clusters(events: list[ClusterEvent], candidates: dict[int, list[int]],
                          representatives: dict[int, ClusterEvent],
                          bodies: dict[int, str | None]) -> Clustering:
    """자료 하나의 사건을 묶음에 배정한다. 후보가 없는 사건은 부르지 않고 새 묶음이다.

    bodies 는 자료 id → 원문이다. 후보가 없으면 쓰지 않는다.
    """
    wanted = {cluster_id for clusters in candidates.values() for cluster_id in clusters}
    found = {cluster_id: event_text(representatives[cluster_id],
                                    bodies.get(representatives[cluster_id].card_id))
             for cluster_id in wanted}
    readable = {cluster_id: text for cluster_id, text in found.items() if text is not None}
    asked = {order: kept for order, clusters in candidates.items()
             if (kept := [c for c in clusters if c in readable])}
    result = Clustering(asked=set(asked))
    result.fixes["representative_unreadable"] = len(found) - len(readable)
    alone: dict[int, int | None] = {event.order_index: None for event in events
                                    if event.order_index not in asked}
    if not asked:
        result.clusters = alone
        return result

    sent = [(event, event_text(event, bodies.get(event.card_id))) for event in events
            if event.order_index in asked]
    if any(text is None for _, text in sent):
        result.error = "원문이 없거나 분류할 때와 달라 사건 문장을 되찾지 못했다"
        return result

    call = await llm.call(llm.SAME_EVENT_STEP, PROMPT_NAME, build_message(sent, asked, readable))
    result.call = call
    if not call.ok:
        result.error = call.error
        return result
    try:
        parsed = parse_assignments(call.raw_response or "", asked)
    except SameEventParseError as exc:
        result.error = llm.parse_failure(call, str(exc))
        return result
    result.clusters = {**alone, **parsed.clusters}
    unreadable = result.fixes["representative_unreadable"]
    result.fixes = {**parsed.fixes, "representative_unreadable": unreadable}
    return result


def _is_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_assignments(text: str, candidates: dict[int, list[int]]) -> Assignments:
    """응답 → 사건별 묶음. candidates 는 LLM 에 보낸 사건 순서 → 후보 묶음 번호다."""
    try:
        data = json.loads(strip_fence(text))
    except json.JSONDecodeError as exc:
        raise SameEventParseError(f"JSON 이 아니다: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("assignments"), list):
        raise SameEventParseError("최상위에 assignments 배열이 없다")

    answers: dict[int, int | None] = {}
    conflicted: set[int] = set()
    fixes = Counter()
    for item in data["assignments"]:
        if not isinstance(item, dict):
            raise SameEventParseError("배정이 객체가 아니다")
        order, cluster = item.get("event"), item.get("cluster")
        if not _is_number(order):
            raise SameEventParseError(f"사건 번호를 알아볼 수 없다: {order!r}")
        if cluster is not None and not _is_number(cluster):
            raise SameEventParseError(f"묶음 번호를 알아볼 수 없다: {cluster!r}")
        if order not in candidates:
            fixes["unknown_dropped"] += 1
            continue
        if cluster is not None and cluster not in candidates[order]:
            fixes["outside_new"] += 1
            cluster = None
        if order in conflicted:
            continue
        if order in answers:
            if answers[order] == cluster:
                fixes["duplicate_dropped"] += 1
            else:
                del answers[order]
                conflicted.add(order)
                fixes["conflict_left"] += 1
            continue
        answers[order] = cluster

    fixes["missing_left"] = len(set(candidates) - set(answers) - conflicted)
    result = Assignments(clusters=answers)
    result.fixes.update(fixes)
    return result
