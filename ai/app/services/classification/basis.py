"""분류 기준 JSON 읽기·검사 (CLASSIFICATION_DB_DRAFT 4-1·4-2·4-7·4-9, 6·7절).

기준 JSON 하나가 산업·종목·별칭·외부 기업·종목–산업 연결·기업–기업 관계의 원본이다.
DB 의 기준표 4개(industries·stock_industries·external_companies·company_relations)는 이 파일에서
넣는다(repositories/classification.py 의 sync_basis). 종목·외부 기업 별칭은 이 파일에만 있다.

버전은 파일 바이트의 sha256 이다. **한 번 만든 파일은 고치지 않는다.** 고칠 일이 생기면 새 날짜의
파일을 만든다. 예전 회차가 어떤 기준으로 분류됐는지는 회차의 basis_version 으로 그 파일을 찾는다.

틀린 기준으로 분류하면 결과 전체를 다시 만들어야 한다. 그래서 읽을 때 CHECK 로 못 거는 규칙까지
전부 검사하고, 하나라도 어긋나면 무엇을 고칠지 모두 모아 알려주고 멈춘다.

기업 관계(company_relations)는 10-29 멘토링 방향대로 **코드 경로가 달라지는 값만 칸으로** 둔다.
(from, to, 종류, 산업) 이 한 행이고, 제품 범위·단계·근거 수준·실제 당사자·기간은 note 에 적는다.
note 는 ④ 판정 입력에 그대로 넘어간다.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

BASIS_DIR = Path(__file__).resolve().parents[2] / "data" / "classification_basis"

EXPOSURES = ("own", "subsidiary", "stake")
STAGES = ("operating", "planned")
RELATION_TYPES = ("supplier", "competitor", "ownership")

CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")  # 산업·외부 기업 코드. 종목코드와 겹치지 않게 소문자로 시작
STOCK_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")  # 2024년부터 영문 대문자가 섞인 코드가 있다(0126Z0)


class BasisError(ValueError):
    """기준 JSON 이 규칙을 어겼다. 어긴 곳을 모두 담는다."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("분류 기준 JSON 오류:\n  " + "\n  ".join(problems))


@dataclass(frozen=True)
class Industry:
    code: str
    name: str
    parent: str | None  # None 이면 맨 위(KRX 업종)
    aliases: tuple[str, ...]  # 조회어. 동의어가 아니다 — 산업보다 좁은 제품명도 들어간다


@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    aliases: tuple[str, ...]  # 회사 자신의 약칭·영문명·옛 이름 (별칭 종류 name)
    subsidiaries: tuple[str, ...]  # 비상장 연결 자회사 이름 (별칭 종류 subsidiary)


@dataclass(frozen=True)
class ExternalCompany:
    code: str
    name: str
    country: str | None
    stock_code: str | None  # 국내 상장사면
    ticker: str | None
    aliases: tuple[str, ...]
    subsidiaries: tuple[str, ...]


@dataclass(frozen=True)
class StockIndustry:
    stock_code: str
    industry_code: str
    exposure: str  # own | subsidiary | stake
    via_company: str | None
    via_stock_code: str | None
    stage: str  # operating | planned
    supply_role: str | None
    source: str
    source_as_of: date
    note: str | None

    @property
    def direct_allowed(self) -> bool:
        """이 연결로 들어온 후보가 DIRECT 를 받을 수 있나(4-8). 상장사 지분·진출 예정은 최대 INDIRECT_CONTEXT."""
        return self.exposure != "stake" and self.stage != "planned"


@dataclass(frozen=True)
class CompanyRelation:
    from_code: str  # 종목코드 또는 외부 기업 코드
    to_code: str
    relation_type: str  # supplier: from 이 to 의 공급사 | competitor | ownership: from 이 to 의 지분을 가짐
    industry_code: str | None
    source: str
    note: str | None
    order: int  # 기준 JSON 순서. 대표 관계를 고를 때 마지막 기준(5-1)


@dataclass(frozen=True)
class Basis:
    version: str  # 파일 sha256
    name: str
    industries: dict[str, Industry]
    stocks: dict[str, Stock]
    externals: dict[str, ExternalCompany]
    stock_industries: tuple[StockIndustry, ...]
    relations: tuple[CompanyRelation, ...]
    blocked_aliases: frozenset[str]  # 여러 회사를 가리켜 문맥 없이 확정하면 안 되는 표기("삼성")
    supply_roles: dict[str, tuple[str, ...]]

    def ancestors(self, industry_code: str) -> list[str]:
        """산업 자신과 상위 산업들. 가까운 것부터."""
        chain = []
        code: str | None = industry_code
        while code is not None:
            chain.append(code)
            code = self.industries[code].parent
        return chain

    def links_of(self, stock_code: str) -> list[StockIndustry]:
        return [link for link in self.stock_industries if link.stock_code == stock_code]

    def display_name(self, code: str) -> str:
        """종목코드·외부 기업 코드 → 이름. 판정 입력과 출력에 쓴다."""
        if code in self.stocks:
            return self.stocks[code].name
        if code in self.externals:
            return self.externals[code].name
        return code


def latest_basis_file() -> Path:
    """기준 폴더에서 이름이 가장 뒤인 파일. 파일 이름이 날짜로 시작한다."""
    files = sorted(BASIS_DIR.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"기준 JSON 이 없다: {BASIS_DIR}")
    return files[-1]


def load_basis(path: Path | None = None) -> Basis:
    path = path or latest_basis_file()
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BasisError([f"JSON 형식이 아니다: {exc}"]) from exc
    return parse_basis(data, version=hashlib.sha256(raw).hexdigest())


def parse_basis(data: dict, *, version: str) -> Basis:
    problems: list[str] = []

    industries: dict[str, Industry] = {}
    for item in data.get("industries", []):
        code = item["code"]
        if not CODE_RE.match(code):
            problems.append(f"산업 code 형식: {code!r} (영문 소문자로 시작, 소문자·숫자·_)")
        if code in industries:
            problems.append(f"산업 code 중복: {code}")
        industries[code] = Industry(
            code=code, name=item["name"], parent=item.get("parent"),
            aliases=tuple(item.get("aliases", [])),
        )
    for industry in industries.values():
        if industry.parent is not None and industry.parent not in industries:
            problems.append(f"산업 {industry.code}: 없는 상위 {industry.parent}")
    problems += _cycles(industries)
    has_children = {i.parent for i in industries.values() if i.parent is not None}

    stocks: dict[str, Stock] = {}
    for item in data.get("stocks", []):
        code = item["code"]
        if not STOCK_CODE_RE.match(code):
            problems.append(f"종목코드 형식: {code!r}")
        if code in stocks:
            problems.append(f"종목코드 중복: {code}")
        stocks[code] = Stock(
            code=code, name=item["name"], aliases=tuple(item.get("aliases", [])),
            subsidiaries=tuple(item.get("subsidiaries", [])),
        )

    externals: dict[str, ExternalCompany] = {}
    for item in data.get("external_companies", []):
        code = item["code"]
        where = f"외부 기업 {code}"
        if not CODE_RE.match(code):
            problems.append(f"{where}: code 형식 (영문 소문자로 시작, 소문자·숫자·_)")
        if code in externals:
            problems.append(f"{where}: code 중복")
        stock_code = item.get("stock_code")
        if stock_code is not None:
            if not STOCK_CODE_RE.match(stock_code):
                problems.append(f"{where}: 종목코드 형식 {stock_code!r}")
            if stock_code in stocks:
                problems.append(f"{where}: {stock_code} 는 분류 대상 종목이다. 외부 기업이 아니라 종목으로 둔다")
            if any(e.stock_code == stock_code for e in externals.values()):
                problems.append(f"{where}: 종목코드 {stock_code} 를 다른 외부 기업이 이미 쓴다")
        externals[code] = ExternalCompany(
            code=code, name=item["name"], country=item.get("country"), stock_code=stock_code,
            ticker=item.get("ticker"), aliases=tuple(item.get("aliases", [])),
            subsidiaries=tuple(item.get("subsidiaries", [])),
        )

    supply_roles = {k: tuple(v) for k, v in data.get("supply_roles", {}).items()}
    for industry_code in supply_roles:
        if industry_code not in industries:
            problems.append(f"supply_roles: 없는 산업 {industry_code}")

    links: list[StockIndustry] = []
    seen_links: set[tuple[str, str]] = set()
    for item in data.get("stock_industries", []):
        link, link_problems = _stock_industry(item)
        problems += link_problems
        if link is None:
            continue
        where = f"연결 {link.stock_code}–{link.industry_code}"
        if (link.stock_code, link.industry_code) in seen_links:
            problems.append(f"{where}: 중복. 두 경로로 걸리면 own > subsidiary > stake 하나만 두고 나머지는 note 에")
        seen_links.add((link.stock_code, link.industry_code))
        stock = stocks.get(link.stock_code)
        if stock is None:
            problems.append(f"{where}: 종목 목록에 없는 종목")
        if link.industry_code not in industries:
            problems.append(f"{where}: 없는 산업")
        elif link.industry_code in has_children:
            problems.append(f"{where}: 아래 단계가 있는 산업에는 연결하지 않는다(가장 작은 분류에 연결)")
        if link.exposure == "subsidiary" and stock and link.via_company not in stock.subsidiaries:
            problems.append(f"{where}: 경유 자회사 {link.via_company!r} 가 그 종목의 subsidiaries 에 없다")
        if link.supply_role is not None and link.supply_role not in supply_roles.get(link.industry_code, ()):
            problems.append(f"{where}: 역할 {link.supply_role!r} 는 supply_roles[{link.industry_code}] 에 없다")
        links.append(link)

    relations: list[CompanyRelation] = []
    seen_relations: set[tuple] = set()
    for order, item in enumerate(data.get("company_relations", [])):
        relation, relation_problems = _relation(item, order, stocks, externals, industries)
        problems += relation_problems
        if relation is None:
            continue
        key = (relation.from_code, relation.to_code, relation.relation_type, relation.industry_code)
        if key in seen_relations:
            problems.append(f"관계 {key}: 중복. (from, to, 종류, 산업) 하나에 한 행 — 범위가 여럿이면 note 에 함께 적는다")
        seen_relations.add(key)
        relations.append(relation)

    problems += _stake_pairs(links, stocks, externals, relations)
    related = {r.from_code for r in relations} | {r.to_code for r in relations}
    for code in externals:
        if code not in related:
            problems.append(f"외부 기업 {code}: 관계가 없다. 출발점으로 쓸 데가 없으므로 넣지 않는다")

    blocked = frozenset(data.get("blocked_aliases", []))
    problems += _alias_conflicts(stocks, externals, industries, blocked)

    if problems:
        raise BasisError(problems)
    return Basis(
        version=version, name=data.get("name", ""), industries=industries, stocks=stocks,
        externals=externals, stock_industries=tuple(links), relations=tuple(relations),
        blocked_aliases=blocked, supply_roles=supply_roles,
    )


def _stock_industry(item: dict) -> tuple[StockIndustry | None, list[str]]:
    where = f"연결 {item.get('stock')}–{item.get('industry')}"
    problems = []
    exposure, stage = item.get("exposure"), item.get("stage")
    via_company, via_stock_code = item.get("via_company"), item.get("via_stock_code")
    if exposure not in EXPOSURES:
        problems.append(f"{where}: exposure {exposure!r} 는 {EXPOSURES} 중 하나")
    if stage not in STAGES:
        problems.append(f"{where}: stage {stage!r} 는 {STAGES} 중 하나")
    if (exposure == "own") != (via_company is None):
        problems.append(f"{where}: 직접 영위(own)가 아니면 via_company 가 있고, own 이면 없다")
    if (exposure == "stake") != (via_stock_code is not None):
        problems.append(f"{where}: 상장사 지분(stake)일 때만 via_stock_code 를 채운다")
    if via_stock_code is not None and via_stock_code == item.get("stock"):
        problems.append(f"{where}: 경유 종목이 자기 자신이다")
    if via_company is not None and not via_company.strip():
        problems.append(f"{where}: via_company 가 빈 문자열")
    source = (item.get("source") or "").strip()
    if not source:
        problems.append(f"{where}: source 가 비었다")
    try:
        as_of = date.fromisoformat(item.get("source_as_of") or "")
    except ValueError:
        problems.append(f"{where}: source_as_of 는 YYYY-MM-DD")
        as_of = None
    if problems:
        return None, problems
    return StockIndustry(
        stock_code=item["stock"], industry_code=item["industry"], exposure=exposure,
        via_company=via_company, via_stock_code=via_stock_code, stage=stage,
        supply_role=item.get("supply_role"), source=source, source_as_of=as_of,
        note=item.get("note"),
    ), []


def _relation(
    item: dict, order: int, stocks: dict, externals: dict, industries: dict,
) -> tuple[CompanyRelation | None, list[str]]:
    a, b, kind = item.get("from"), item.get("to"), item.get("type")
    where = f"관계 {a}→{b} {kind}"
    problems = []
    for code in (a, b):
        if code not in stocks and code not in externals:
            problems.append(f"{where}: {code!r} 는 종목도 외부 기업도 아니다")
    if a not in stocks and b not in stocks:
        problems.append(f"{where}: 적어도 한쪽은 분류 대상 종목이어야 한다")
    if a == b:
        problems.append(f"{where}: 자기 자신과의 관계")
    if kind not in RELATION_TYPES:
        problems.append(f"{where}: type 은 {RELATION_TYPES} 중 하나")
    industry = item.get("industry")
    if industry is not None and industry not in industries:
        problems.append(f"{where}: 없는 산업 {industry}")
    source = (item.get("source") or "").strip()
    if not source:
        problems.append(f"{where}: source 가 비었다")
    if problems:
        return None, problems
    # 방향이 없는 관계는 한 행만 둔다. 외부 기업과는 종목 쪽, 종목끼리는 코드가 작은 쪽이 from (4-7)
    if kind == "competitor" and (a not in stocks or (b in stocks and b < a)):
        a, b = b, a
    return CompanyRelation(
        from_code=a, to_code=b, relation_type=kind, industry_code=industry, source=source,
        note=item.get("note"), order=order,
    ), []


def _stake_pairs(
    links: list[StockIndustry], stocks: dict, externals: dict, relations: list[CompanyRelation],
) -> list[str]:
    """상장사 지분(stake) 연결에는 같은 지분의 ownership 관계가 있어야 한다(4-2, INDUSTRY_REVIEW 2-5).

    산업 기사와 회사 기사가 같은 지분을 다르게 보지 않게 한다.
    """
    problems = []
    by_stock_code = {e.stock_code: e.code for e in externals.values() if e.stock_code}
    owned = {(r.from_code, r.to_code) for r in relations if r.relation_type == "ownership"}
    for link in links:
        if link.exposure != "stake":
            continue
        where = f"연결 {link.stock_code}–{link.industry_code}"
        target = link.via_stock_code if link.via_stock_code in stocks else by_stock_code.get(link.via_stock_code)
        if target is None:
            problems.append(f"{where}: 경유 상장사 {link.via_stock_code} 가 종목도 외부 기업도 아니다")
        elif (link.stock_code, target) not in owned:
            problems.append(f"{where}: 짝이 되는 ownership 관계 {link.stock_code}→{target} 가 없다")
    return problems


def _cycles(industries: dict[str, Industry]) -> list[str]:
    problems = []
    for start in industries:
        seen = set()
        code: str | None = start
        while code is not None and code in industries:
            if code in seen:
                problems.append(f"산업 상위 관계가 고리를 이룬다: {start}")
                break
            seen.add(code)
            code = industries[code].parent
    return problems


def alias_entries(
    stocks: dict, externals: dict, industries: dict, blocked: frozenset[str],
) -> list[tuple[str, str, str, str | None]]:
    """(표기, 대상 종류, 코드, 자회사 이름) 목록. 막은 표기와 같은 공식 이름("SK")은 넣지 않는다."""
    blocked_keys = {normalize_mention(b) for b in blocked}
    entries = []
    for kind, companies in (("stock", stocks), ("external", externals)):
        for company in companies.values():
            if normalize_mention(company.name) not in blocked_keys:
                entries.append((company.name, kind, company.code, None))
            entries += [(alias, kind, company.code, None) for alias in company.aliases]
            entries += [(sub, kind, company.code, sub) for sub in company.subsidiaries]
    for industry in industries.values():
        entries += [(alias, "industry", industry.code, None) for alias in industry.aliases]
    return entries


def _alias_conflicts(
    stocks: dict, externals: dict, industries: dict, blocked: frozenset[str],
) -> list[str]:
    """한 표기는 대상 하나만 가리켜야 한다. 막은 표기는 별칭으로 쓸 수 없다."""
    problems = []
    owner: dict[str, tuple] = {}
    blocked_keys = {normalize_mention(b) for b in blocked}
    for alias, kind, code, sub in alias_entries(stocks, externals, industries, blocked):
        key = normalize_mention(alias)
        target = (kind, code, sub)
        if not key:
            problems.append(f"{kind} {code}: 빈 표기")
            continue
        if key in blocked_keys:
            problems.append(f"{kind} {code}: 막은 표기 {alias!r} 를 별칭으로 쓸 수 없다")
        if key in owner and owner[key] != target:
            problems.append(f"표기 {alias!r} 가 {owner[key][:2]} 와 {target[:2]} 를 함께 가리킨다")
        owner.setdefault(key, target)
    return problems


def normalize_mention(text: str) -> str:
    """표기 비교용. 앞뒤 공백과 영문 대소문자만 무시한다. 띄어쓰기·조사는 건드리지 않는다."""
    return text.strip().casefold()
