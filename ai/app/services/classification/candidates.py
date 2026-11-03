"""③ 후보 종목 모으기 (CLASSIFICATION_DB_DRAFT 5-1). LLM 을 부르지 않는다.

**기준표는 후보를 만드는 데만 쓴다(전제 P11).** 붙일지는 ④ 가 사건마다 판정한다.

    company   사건 대상(②)에 종목이 있다
    industry  scope = industry 이고, 대상 산업이 종목 산업 자신이거나 그 상위    ◀ stock_industries
    relation  직접 언급된 종목·외부 기업에서 1-hop 관계인 종목 (양방향)           ◀ company_relations

- 후보는 기준 JSON 의 종목(30종목)뿐이다. 외부 기업은 출발점일 뿐 후보가 되지 않는다(전제 P15).
- macro·market 사건은 후보를 만들지 않는다. 조회 때 모든 종목에 공통 배경으로 붙는다.
- 회사 사건에 산업 표기가 섞여도 industry 경로를 타지 않는다. 다른 회사로 퍼지지 않게 한다.
- 형제 세부 산업으로는 넓히지 않는다("중·저사양 FC-BGA" 기사는 고사양 종목의 후보가 아니다).
- relation 경로는 사건에 직접 언급된 기업에서만 출발한다(industry 경로 종목에서 다시 넓히면 2-hop).
  등락만 말하는 사건(role = price_move)은 관계로 넘기지 않는다.
- 자회사 표기로 들어온 종목은 공급·경쟁 관계를 그 자회사를 거친 산업 연결의 산업으로만 탄다.
  지분 관계는 제한하지 않는다. 10-29 에 관계의 실제 당사자를 note 로 옮겼으므로 "실제 당사자 일치"
  조건(5-1 의 (1))은 코드로 볼 수 없다. 외부 기업의 자회사 표기(삼성바이오에피스)는 그래서 제한하지 않는다.
- 한 종목이 여러 경로에 걸리면 위쪽 경로 하나가 대표다(company > industry > relation). 대표 경로는
  direct_allowed 와 저장 칸만 정하고, 관계로도 걸렸으면 그 관계는 relation_refs 에 모두 남긴다.
"""

from dataclasses import dataclass, field

from app.services.classification.basis import Basis, CompanyRelation, StockIndustry
from app.services.classification.events import Event
from app.services.classification.link import EntityLink

PATHS = ("company", "industry", "relation")
# 관계로 넘기지 않는 역할. "B사 주가 3% 하락" 은 관계 회사에 대한 정보가 아니다
NO_RELATION_ROLES = frozenset({"price_move"})
NO_CANDIDATE_SCOPES = frozenset({"macro", "market"})


@dataclass
class Candidate:
    stock_code: str
    path: str  # company | industry | relation
    direct_allowed: bool
    industry_code: str | None = None  # industry 경로: 고른 연결의 산업
    link: StockIndustry | None = None  # industry 경로: 고른 연결
    via_subsidiaries: tuple[str, ...] = ()  # company 경로: 자회사 표기로 잡혔으면 그 이름들
    via_stock_code: str | None = None  # relation 경로: 대표 관계의 출발 종목
    via_external_code: str | None = None  # relation 경로: 대표 관계의 출발 외부 기업
    relation_type: str | None = None  # relation 경로: 대표 관계의 종류
    relation_refs: list[dict] = field(default_factory=list)  # 걸린 관계 전부. 경로와 상관없이 남긴다


def relation_ref(relation: CompanyRelation, origin: str, candidate: str) -> dict:
    """판정에 넘기는 관계 하나. candidate_is 는 출발점에서 본 후보의 자리다."""
    if relation.relation_type == "supplier":
        role = "supplier" if relation.from_code == candidate else "customer"
    elif relation.relation_type == "ownership":
        role = "owner" if relation.from_code == candidate else "owned"
    else:
        role = "competitor"
    return {"via": origin, "type": relation.relation_type, "candidate_is": role,
            "industry": relation.industry_code, "note": relation.note}


def _origins(links: list[EntityLink], basis: Basis) -> dict[str, frozenset[str] | None]:
    """관계 경로의 출발점 → 공급·경쟁 관계를 탈 수 있는 산업. None 이면 제한 없음.

    같은 종목이 자회사 표기와 자기 이름으로 함께 나왔으면 제한하지 않는다.
    """
    subs: dict[str, set[str]] = {}
    unrestricted: set[str] = set()
    for link in links:
        if link.external_code:
            unrestricted.add(link.external_code)
        elif link.stock_code:
            if link.via_subsidiary:
                subs.setdefault(link.stock_code, set()).add(link.via_subsidiary)
            else:
                unrestricted.add(link.stock_code)
    origins: dict[str, frozenset[str] | None] = dict.fromkeys(unrestricted)
    for stock, names in subs.items():
        if stock in origins:
            continue
        origins[stock] = frozenset(
            link.industry_code for link in basis.links_of(stock)
            if link.exposure == "subsidiary" and link.via_company in names
        )
    return origins


def collect_candidates(event: Event, links: list[EntityLink], basis: Basis) -> list[Candidate]:
    if event.scope in NO_CANDIDATE_SCOPES:
        return []
    found: dict[str, Candidate] = {}

    # company — 사건 대상에 종목이 있다
    for link in links:
        if link.stock_code and link.stock_code in basis.stocks:
            candidate = found.setdefault(
                link.stock_code, Candidate(link.stock_code, "company", direct_allowed=True))
            if link.via_subsidiary and link.via_subsidiary not in candidate.via_subsidiaries:
                candidate.via_subsidiaries += (link.via_subsidiary,)

    # industry — 산업 사건만. 대상 산업이 종목 연결 산업의 자신이거나 상위
    if event.scope == "industry":
        targets = {link.industry_code for link in links if link.industry_code}
        chosen: dict[str, StockIndustry] = {}
        for stock_link in basis.stock_industries:  # 기준 JSON 순서
            if not targets.intersection(basis.ancestors(stock_link.industry_code)):
                continue
            current = chosen.get(stock_link.stock_code)
            # DIRECT 가 가능한 연결을 먼저, 그 안에서는 기준 JSON 순서
            if current is None or (stock_link.direct_allowed and not current.direct_allowed):
                chosen[stock_link.stock_code] = stock_link
        for stock, stock_link in chosen.items():
            if stock not in found:
                found[stock] = Candidate(stock, "industry", stock_link.direct_allowed,
                                         industry_code=stock_link.industry_code, link=stock_link)

    # relation — 직접 언급된 기업에서 1-hop
    if event.role not in NO_RELATION_ROLES:
        origins = _origins(links, basis)
        refs: dict[str, list[tuple[tuple, dict, CompanyRelation, str]]] = {}
        for relation in basis.relations:
            for origin, other in ((relation.from_code, relation.to_code),
                                  (relation.to_code, relation.from_code)):
                if origin not in origins or other not in basis.stocks:
                    continue
                allowed = origins[origin]
                if (allowed is not None and relation.relation_type != "ownership"
                        and relation.industry_code not in allowed):
                    continue
                # 대표 관계: 출발점이 종목인 관계 먼저, 그 안에서는 기준 JSON 순서
                key = (0 if origin in basis.stocks else 1, relation.order)
                refs.setdefault(other, []).append(
                    (key, relation_ref(relation, origin, other), relation, origin))
        for stock, items in refs.items():
            items.sort(key=lambda item: item[0])
            if stock not in found:
                _, _, relation, origin = items[0]
                found[stock] = Candidate(
                    stock, "relation", direct_allowed=False,
                    via_stock_code=origin if origin in basis.stocks else None,
                    via_external_code=origin if origin in basis.externals else None,
                    relation_type=relation.relation_type,
                )
            found[stock].relation_refs = [ref for _, ref, _, _ in items]

    return sorted(found.values(), key=lambda c: PATHS.index(c.path))
