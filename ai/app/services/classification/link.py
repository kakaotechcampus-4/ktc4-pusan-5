"""기사 속 표기 → 종목·산업 (전제 P4, DRAFT 6절).

LLM 이 아니라 기준 JSON 의 별칭이 정한다. 어느 별칭에도 안 걸린 표기는 대상을 만들지 않고
`unresolved` 로 돌려준다. 사람이 보고 별칭을 더한 뒤 재분류한다.

`linked_by = "alias"` 만 있다. LLM 이 허용 code 목록에서 고르는 방식(Jev, INDUSTRY_MAP 8절)을
들이면 같은 EntityLink 를 `linked_by` 만 바꿔 내면 된다. 조립(assemble)은 연결 방식을 보지 않는다.
"""

from dataclasses import dataclass

from app.services.classification.basis import Basis, normalize_mention


@dataclass(frozen=True)
class EntityLink:
    mention: str
    stock_code: str | None = None
    industry_code: str | None = None
    linked_by: str = "alias"


@dataclass(frozen=True)
class LinkResult:
    links: list[EntityLink]
    unresolved: list[str]  # 막은 표기("삼성")와 사전에 없는 표기


def alias_index(basis: Basis) -> dict[str, EntityLink]:
    """정규화한 표기 → 대상. 기준을 읽을 때 겹침을 이미 막았으므로 한 표기에 대상 하나다."""
    index: dict[str, EntityLink] = {}
    for stock in basis.stocks.values():
        for name in (stock.name, *stock.aliases):
            index[normalize_mention(name)] = EntityLink(mention=name, stock_code=stock.code)
    for industry in basis.industries.values():
        for alias in industry.aliases:
            index[normalize_mention(alias)] = EntityLink(mention=alias, industry_code=industry.code)
    return index


def link_mentions(mentions: tuple[str, ...] | list[str], basis: Basis,
                  index: dict[str, EntityLink] | None = None) -> LinkResult:
    index = index if index is not None else alias_index(basis)
    links: list[EntityLink] = []
    unresolved: list[str] = []
    for mention in mentions:
        target = index.get(normalize_mention(mention))
        if target is None:
            unresolved.append(mention)
            continue
        # 저장할 mention 은 기사 표기 그대로다. 사건의 mentions 와 비교해 미연결을 찾기 때문이다
        links.append(EntityLink(
            mention=mention, stock_code=target.stock_code, industry_code=target.industry_code,
        ))
    return LinkResult(links=links, unresolved=unresolved)
