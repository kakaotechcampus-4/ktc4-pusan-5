"""분류 기준 JSON 읽기·검사.

기준 JSON 하나가 종목·별칭·산업·종목–산업 연결의 원본이다(DRAFT 7절). DB 의 기준표는
나중에 이 파일에서 넣는다. 버전은 파일 바이트의 sha256 이고, 한 번 만든 파일은 고치지 않는다.

INDUSTRY_MAP 2026-10-12 보완을 반영해 DRAFT 4-1 과 두 군데가 다르다.
    - KRX 표시 그룹(`krx_groups`)과 뉴스용 상위 산업(`parent`)을 나눈다. 조회는 뉴스용 상위만 탄다
    - 연결마다 유형·근거·검토 상태를 담는다. **확인(`confirmed`)된 연결만 조립에 쓴다**

틀린 기준으로 분류하면 결과 전체를 다시 만들어야 한다. 그래서 읽을 때 전부 검사하고,
하나라도 어긋나면 무엇을 고칠지 모두 모아 알려주고 멈춘다.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# INDUSTRY_MAP 1-1 의 연결 유형
LINK_TYPES = ("business", "ownership", "supply_chain")
# INDUSTRY_MAP 1-1 의 검토 상태. 미검토 / 확인 / 보류 / 제외
LINK_STATUSES = ("unreviewed", "confirmed", "on_hold", "excluded")
STOCK_CODE_LEN = 6


class BasisError(ValueError):
    """기준 JSON 이 규칙을 어겼다. 어긴 곳을 모두 담는다."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("분류 기준 JSON 오류:\n  " + "\n  ".join(problems))


@dataclass(frozen=True)
class Industry:
    code: str
    name: str
    krx_group: str  # 화면 표시용 KRX 업종. 조회 경로에는 쓰지 않는다
    parent: str | None  # 뉴스용 상위 산업. 없으면 최상위
    aliases: tuple[str, ...]  # 검토된 산업 표기만. INDUSTRY_MAP 의 기사 표현 예시를 그대로 넣지 않는다


@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    aliases: tuple[str, ...]  # 종목명 말고 기사에 나오는 표기


@dataclass(frozen=True)
class StockIndustryLink:
    stock_code: str
    industry_code: str
    link_type: str
    status: str
    evidence: str | None  # 사업보고서 절·공시번호·IR 주소
    reviewed_by: str | None
    reviewed_on: str | None


@dataclass(frozen=True)
class Basis:
    version: str  # 파일 sha256
    name: str
    krx_groups: dict[str, str]  # code → 이름(BE sector 값)
    industries: dict[str, Industry]
    stocks: dict[str, Stock]
    links: tuple[StockIndustryLink, ...]
    blocked_aliases: frozenset[str]  # 여러 회사를 가리켜 확정하면 안 되는 표기("삼성")

    def ancestors(self, industry_code: str) -> list[str]:
        """산업 자신과 뉴스용 상위 산업들. 가까운 것부터. KRX 표시 그룹은 넣지 않는다."""
        chain = []
        code: str | None = industry_code
        while code is not None:
            chain.append(code)
            code = self.industries[code].parent
        return chain

    def industries_of(self, stock_code: str) -> list[str]:
        """종목에 **확인된** 연결의 산업. 미검토·보류·제외는 없는 것으로 본다."""
        return [link.industry_code for link in self.links
                if link.stock_code == stock_code and link.status == "confirmed"]

    def reachable_industries(self, stock_code: str) -> set[str]:
        """산업 경로로 이 종목에 닿는 산업: 종목의 산업과 그 상위. 형제 산업은 넣지 않는다."""
        return {code for own in self.industries_of(stock_code) for code in self.ancestors(own)}


def load_basis(path: Path) -> Basis:
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BasisError([f"JSON 형식이 아니다: {exc}"]) from exc
    return parse_basis(data, version=hashlib.sha256(raw).hexdigest())


def parse_basis(data: dict, *, version: str) -> Basis:
    problems: list[str] = []

    krx_groups: dict[str, str] = {}
    for group in data.get("krx_groups", []):
        if group["code"] in krx_groups:
            problems.append(f"KRX 그룹 code 중복: {group['code']}")
        krx_groups[group["code"]] = group["name"]

    industries: dict[str, Industry] = {}
    for item in data.get("industries", []):
        code = item["code"]
        if code in industries or code in krx_groups:
            problems.append(f"산업 code 중복: {code}")
        industries[code] = Industry(
            code=code,
            name=item["name"],
            krx_group=item["krx_group"],
            parent=item.get("parent"),
            aliases=tuple(item.get("aliases", [])),
        )
    for industry in industries.values():
        if industry.krx_group not in krx_groups:
            problems.append(f"산업 {industry.code}: 없는 KRX 그룹 {industry.krx_group}")
        if industry.parent is not None and industry.parent not in industries:
            # KRX 그룹을 parent 로 적은 경우도 여기 걸린다 — 표시 그룹은 조회 경로가 아니다
            problems.append(f"산업 {industry.code}: 상위 {industry.parent} 가 뉴스용 산업 목록에 없다")
    problems += _cycles(industries)

    stocks: dict[str, Stock] = {}
    for item in data.get("stocks", []):
        code = item["code"]
        if len(code) != STOCK_CODE_LEN:
            problems.append(f"종목코드는 {STOCK_CODE_LEN}자리다: {code}")
        if code in stocks:
            problems.append(f"종목코드 중복: {code}")
        stocks[code] = Stock(code=code, name=item["name"], aliases=tuple(item.get("aliases", [])))

    links: list[StockIndustryLink] = []
    seen_links: set[tuple[str, str]] = set()
    for item in data.get("links", []):
        link = StockIndustryLink(
            stock_code=item["stock_code"],
            industry_code=item["industry_code"],
            link_type=item["link_type"],
            status=item["status"],
            evidence=item.get("evidence"),
            reviewed_by=item.get("reviewed_by"),
            reviewed_on=item.get("reviewed_on"),
        )
        where = f"연결 {link.stock_code}–{link.industry_code}"
        if (link.stock_code, link.industry_code) in seen_links:
            problems.append(f"{where}: 중복")
        seen_links.add((link.stock_code, link.industry_code))
        if link.stock_code not in stocks:
            problems.append(f"{where}: 종목 목록에 없는 종목")
        if link.industry_code not in industries:
            problems.append(f"{where}: 뉴스용 산업 목록에 없는 산업(KRX 그룹에는 연결하지 않는다)")
        if link.link_type not in LINK_TYPES:
            problems.append(f"{where}: 연결 유형 {link.link_type!r} 는 {LINK_TYPES} 중 하나")
        if link.status not in LINK_STATUSES:
            problems.append(f"{where}: 검토 상태 {link.status!r} 는 {LINK_STATUSES} 중 하나")
        if link.status == "confirmed" and not (link.evidence and link.reviewed_by and link.reviewed_on):
            # INDUSTRY_MAP 1-1: 근거·확인자·확인일 없는 확인은 운영 승인으로 보지 않는다
            problems.append(f"{where}: confirmed 인데 evidence·reviewed_by·reviewed_on 이 비었다")
        links.append(link)

    blocked = frozenset(data.get("blocked_aliases", []))
    problems += _alias_conflicts(stocks, industries, blocked)

    if problems:
        raise BasisError(problems)
    return Basis(
        version=version,
        name=data.get("name", ""),
        krx_groups=krx_groups,
        industries=industries,
        stocks=stocks,
        links=tuple(links),
        blocked_aliases=blocked,
    )


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


def _alias_conflicts(
    stocks: dict[str, Stock], industries: dict[str, Industry], blocked: frozenset[str],
) -> list[str]:
    """한 표기는 대상 하나만 가리켜야 한다. 막은 표기는 어디에도 넣지 않는다."""
    owner: dict[str, str] = {}
    problems = []
    entries = [(name, f"종목 {s.code}") for s in stocks.values() for name in (s.name, *s.aliases)]
    entries += [(alias, f"산업 {i.code}") for i in industries.values() for alias in i.aliases]
    blocked_keys = {normalize_mention(b) for b in blocked}
    for alias, target in entries:
        key = normalize_mention(alias)
        if not key:
            problems.append(f"{target}: 빈 표기")
            continue
        if key in blocked_keys:
            problems.append(f"{target}: 막은 표기 {alias!r} 를 별칭으로 쓸 수 없다")
        if key in owner and owner[key] != target:
            problems.append(f"표기 {alias!r} 가 {owner[key]} 와 {target} 를 함께 가리킨다")
        owner.setdefault(key, target)
    return problems


def normalize_mention(text: str) -> str:
    """표기 비교용. 앞뒤 공백과 영문 대소문자만 무시한다. 띄어쓰기·조사는 건드리지 않는다."""
    return text.strip().casefold()
