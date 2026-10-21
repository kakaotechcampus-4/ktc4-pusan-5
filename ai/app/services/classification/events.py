"""LLM 이 낸 사건 목록을 검사한다.

LLM 은 기사마다 한 번 불러 사건 목록을 받는다(전제 P3). 응답 모양은 프롬프트
llm/prompts/classification_events.md 의 출력 절과 같다. 사건 형식은 실험 E2·E3 로 확정하므로
(전제 P10) 프롬프트의 형식을 바꾸면 여기도 같이 고친다.

    {"events": [
        {"scope": "industry", "role": "cause", "tense": "past",
         "sentences": [1], "context": [], "mentions": ["D램"], "reason": "..."}
    ]}

검사 결과는 둘 중 하나다.
    - 형식이 깨졌으면 EventParseError → 회차 status = failed. 원문 응답은 그대로 남긴다
    - 형식이 맞으면 Event 목록. 원문에 없는 표기는 빼고, 뺀 것을 따로 돌려준다
"""

import json
import re
from dataclasses import dataclass

SCOPES = ("company", "industry", "macro", "market")
ROLES = ("cause", "price_move", "outlook", "context", "analyst_view")
# 값 이름을 role(cause·outlook …)과 헷갈리지 않는 말로 골랐다. happened·expected 였을 때
# 모델이 role 칸에 tense 값을 넣는 실수를 했다(2026-10-21, 3건 중 2건 실패)
TENSES = ("past", "future")

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class EventParseError(ValueError):
    """응답 형식이 깨졌다. 이 회차는 실패로 남긴다."""


@dataclass(frozen=True)
class Event:
    order_index: int  # 1부터
    scope: str
    role: str
    tense: str
    sentence_indices: tuple[int, ...]  # 정렬·중복 제거됨
    context_indices: tuple[int, ...]
    mentions: tuple[str, ...]  # 원문에 있는 것만
    reason: str | None


@dataclass(frozen=True)
class ParsedEvents:
    events: list[Event]
    # 원문에 없어서 뺀 표기 (사건 순서, 표기). LLM 이 지어낸 표기를 추적할 때 본다
    dropped_mentions: list[tuple[int, str]]


def parse_events(response: str, sentences: list[str], title: str = "") -> ParsedEvents:
    """응답 텍스트 → 사건 목록. sentences 는 LLM 에 넣은 그 문장들(splitter 결과)이다.

    표기는 제목에서도 찾는다. 회사 이름이 제목에만 있고 본문은 "회사는" 으로 쓰는 기사가 흔하다.
    근거 번호는 본문 문장만 가리킨다 — 제목은 번호가 없다.
    """
    text = response.strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EventParseError(f"JSON 이 아니다: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise EventParseError("최상위에 events 배열이 없다")

    body = "\n".join([title, *sentences])
    events: list[Event] = []
    dropped: list[tuple[int, str]] = []
    for order, item in enumerate(data["events"], start=1):
        if not isinstance(item, dict):
            raise EventParseError(f"사건 {order}: 객체가 아니다")
        scope = _choice(item, "scope", SCOPES, order)
        role = _choice(item, "role", ROLES, order)
        tense = _choice(item, "tense", TENSES, order)
        indices = _indices(item.get("sentences"), len(sentences), order, "sentences")
        if not indices:
            raise EventParseError(f"사건 {order}: 근거 문장이 없다")
        context = _indices(item.get("context", []), len(sentences), order, "context")

        mentions: list[str] = []
        raw_mentions = item.get("mentions", [])
        if not isinstance(raw_mentions, list):
            raise EventParseError(f"사건 {order}: mentions 가 배열이 아니다")
        for mention in raw_mentions:
            if not isinstance(mention, str) or not mention.strip():
                continue
            mention = mention.strip()
            # 표기는 기사 전체에서 찾는다. 근거 문장이 대명사("이 회사")일 수 있어서다
            if mention in body:
                if mention not in mentions:
                    mentions.append(mention)
            else:
                dropped.append((order, mention))

        reason = item.get("reason")
        events.append(Event(
            order_index=order,
            scope=scope,
            role=role,
            tense=tense,
            sentence_indices=indices,
            context_indices=tuple(i for i in context if i not in indices),
            mentions=tuple(mentions),
            reason=reason if isinstance(reason, str) and reason.strip() else None,
        ))
    return ParsedEvents(events=events, dropped_mentions=dropped)


def _choice(item: dict, key: str, allowed: tuple[str, ...], order: int) -> str:
    value = item.get(key)
    if value not in allowed:
        raise EventParseError(f"사건 {order}: {key}={value!r} 는 {allowed} 중 하나여야 한다")
    return value


def _indices(value: object, count: int, order: int, key: str) -> tuple[int, ...]:
    """번호 목록을 정렬·중복 제거한다. 범위 밖 번호는 응답 실패로 본다 — 없는 문장을 가리킨다."""
    if not isinstance(value, list):
        raise EventParseError(f"사건 {order}: {key} 가 배열이 아니다")
    out = set()
    for index in value:
        # bool 은 int 의 하위 타입이라 따로 막는다
        if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= count:
            raise EventParseError(f"사건 {order}: {key} 의 {index!r} 는 1~{count} 범위의 번호가 아니다")
        out.add(index)
    return tuple(sorted(out))
