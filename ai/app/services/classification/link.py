"""② 기사 속 표기 → 종목·산업·외부 기업 (전제 P4, CLASSIFICATION_DB_DRAFT 6절).

    별칭 사전(기준 JSON) → 안 잡히면 LLM 이 코드 목록에서 고름(linked_by = llm_code)
                         → 그래도 안 잡히면 대상을 만들지 않는다(사건의 mentions 에는 남는다)

- 자회사 별칭(subsidiaries)으로 잡히면 모회사(또는 외부 기업)에 잇고 via_subsidiary 에 자회사 이름을 남긴다.
- "삼성" 처럼 막은 표기(blocked_aliases)는 문맥이 있어도 특정 회사로 확정하지 않는다. LLM 에도 보내지 않는다.
- LLM 코드 선택은 company·industry 사건의 표기만 보낸다. 거시·시장 사건은 모든 종목에 붙으므로 대상이 필요 없다.
- LLM 이 목록 밖 코드를 내면 버린다. 산업은 맨 위(KRX 업종)를 목록에서 뺀다 — 업종 전체로 퍼지는 연결을 막는다.

이 모듈의 LLM 이 예전 문서(INDUSTRY_MAP)에서 "Jev" 라고 부르던 역할이다.
"""

import json
from dataclasses import dataclass

from app.services.classification import llm
from app.services.classification.basis import Basis, alias_entries, normalize_mention
from app.services.classification.events import Event, strip_fence

PROMPT_NAME = "classification_link"
LINKED_BY = ("alias", "llm_code")
# 대상이 필요한 사건. 거시·시장 사건은 판정하지 않고 모든 종목에 공통 배경으로 붙는다
TARGET_SCOPES = ("company", "industry")


@dataclass(frozen=True)
class EntityLink:
    mention: str  # 기사 표기 그대로. 사건의 mentions 중 하나
    stock_code: str | None = None
    industry_code: str | None = None
    external_code: str | None = None
    linked_by: str = "alias"
    via_subsidiary: str | None = None  # 자회사 별칭으로 잡혔을 때 그 자회사 이름


@dataclass(frozen=True)
class LinkResult:
    links: list[EntityLink]
    unresolved: list[str]  # 사전에 없는 표기. LLM 코드 선택으로 넘긴다
    blocked: list[str]  # 막은 표기. 어디에도 잇지 않는다


def alias_index(basis: Basis) -> dict[str, EntityLink]:
    """정규화한 표기 → 대상. 기준을 읽을 때 겹침을 이미 막았으므로 한 표기에 대상 하나다."""
    index: dict[str, EntityLink] = {}
    for alias, kind, code, sub in alias_entries(basis.stocks, basis.externals, basis.industries,
                                                basis.blocked_aliases):
        index[normalize_mention(alias)] = EntityLink(mention=alias, via_subsidiary=sub, **{
            "stock": {"stock_code": code}, "external": {"external_code": code},
            "industry": {"industry_code": code},
        }[kind])
    return index


def link_mentions(mentions: tuple[str, ...] | list[str], basis: Basis,
                  index: dict[str, EntityLink] | None = None) -> LinkResult:
    index = index if index is not None else alias_index(basis)
    blocked_keys = {normalize_mention(b) for b in basis.blocked_aliases}
    links, unresolved, blocked = [], [], []
    for mention in mentions:
        key = normalize_mention(mention)
        if key in blocked_keys:
            blocked.append(mention)
            continue
        target = index.get(key)
        if target is None:
            unresolved.append(mention)
            continue
        # 저장할 mention 은 기사 표기 그대로다. 사건의 mentions 와 비교해 미연결을 찾기 때문이다
        links.append(EntityLink(
            mention=mention, stock_code=target.stock_code, industry_code=target.industry_code,
            external_code=target.external_code, via_subsidiary=target.via_subsidiary,
        ))
    return LinkResult(links=links, unresolved=unresolved, blocked=blocked)


# ── LLM 코드 선택 ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Unresolved:
    event_order: int
    mention: str


@dataclass
class CodeLinking:
    call: llm.StepCall | None  # 보낼 표기가 없으면 부르지 않는다
    links: dict[int, list[EntityLink]]  # 사건 순서 → 고른 대상
    error: str | None = None


def code_list(basis: Basis) -> str:
    """LLM 에 주는 선택지. 맨 위 산업(KRX 업종)은 넣지 않는다."""
    lines = ["## 종목"]
    lines += [f"{s.code} {s.name}" for s in basis.stocks.values()]
    lines.append("\n## 외부 기업 (분류 대상 종목이 아닌 회사)")
    lines += [f"{e.code} {e.name}" for e in basis.externals.values()]
    lines.append("\n## 산업")
    for industry in basis.industries.values():
        if industry.parent is None:
            continue
        parent = basis.industries[industry.parent].name
        lines.append(f"{industry.code} {industry.name} (상위: {parent})")
    return "\n".join(lines)


def build_link_message(items: list[Unresolved], events: dict[int, Event], sentences: list[str],
                       basis: Basis) -> str:
    blocks = []
    for item in items:
        event = events[item.event_order]
        text = " ".join(sentences[i - 1] for i in (*event.context_indices, *event.sentence_indices))
        blocks.append(f"- 사건 {item.event_order} ({event.scope}) 표기 \"{item.mention}\"\n  문장: {text}")
    return f"{code_list(basis)}\n\n# 고를 표기\n" + "\n".join(blocks)


def parse_link_response(text: str, items: list[Unresolved], basis: Basis) -> dict[int, list[EntityLink]]:
    """목록 밖 코드·요청하지 않은 표기는 버린다. 형식이 깨지면 ValueError."""
    data = json.loads(strip_fence(text))
    if not isinstance(data, dict) or not isinstance(data.get("links"), list):
        raise ValueError("최상위에 links 배열이 없다")  # noqa: TRY004 — 응답 형식 오류로 함께 잡는다
    asked = {(i.event_order, i.mention) for i in items}
    industries = {code for code, i in basis.industries.items() if i.parent is not None}
    out: dict[int, list[EntityLink]] = {}
    seen = set()
    for item in data["links"]:
        if not isinstance(item, dict):
            continue
        key = (item.get("event"), item.get("mention"))
        code = item.get("code")
        if key not in asked or not isinstance(code, str) or key in seen:
            continue
        if code in basis.stocks:
            link = EntityLink(mention=key[1], stock_code=code, linked_by="llm_code")
        elif code in basis.externals:
            link = EntityLink(mention=key[1], external_code=code, linked_by="llm_code")
        elif code in industries:
            link = EntityLink(mention=key[1], industry_code=code, linked_by="llm_code")
        else:
            continue
        seen.add(key)
        out.setdefault(key[0], []).append(link)
    return out


async def link_with_llm(items: list[Unresolved], events: dict[int, Event], sentences: list[str],
                        basis: Basis, *, model: str | None = None) -> CodeLinking:
    if not items:
        return CodeLinking(call=None, links={})
    call = await llm.call("link", PROMPT_NAME, build_link_message(items, events, sentences, basis),
                          model=model)
    if not call.ok:
        return CodeLinking(call=call, links={}, error=call.error)
    try:
        links = parse_link_response(call.raw_response or "", items, basis)
    except ValueError as exc:
        return CodeLinking(call=call, links={}, error=llm.parse_failure(call, f"응답 형식 오류: {exc}"))
    return CodeLinking(call=call, links=links)
