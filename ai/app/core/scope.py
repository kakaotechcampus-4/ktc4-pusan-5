"""수집 범위와 출처별 이용 조건. `ai/collection_scope.toml` 을 읽는다.

모든 자료를 계속 쌓는 것을 기본으로 삼지 않는다. 팀이 정한
출처·종목·채널·기간·수집량 안에서만 수집하고, 그 범위를 이 파일 하나에 적는다. 수집기는
시작할 때 범위를 확인하고, 범위 밖이면 수집하지 않는다.

    출처(sources)     켜지 않은 출처는 수집하지 않는다. 파일이 비어 있으면 아무것도 받지 않는다
    종목·채널         출처마다 허용 목록이 있다(SOURCES). 목록에 없는 검색어·채널은 거부한다
    기간(period)      자료 날짜(기사 발행일·메시지 게시일·리포트 작성일, KST) 기준. 양 끝 포함
    수집량(max_items) 그 경로로 DB 에 쌓인 행 수의 상한(누적). 닿으면 새 자료를 받지 않는다.
                      보관 정책으로 본문을 지운 행도 센다 — 지웠다고 더 모으면 계속 쌓는 것이다

이용 조건(terms)은 켠 출처마다 반드시 적는다. "미확인" 이어도 된다 — 확인하지 않았다는 사실을
기록하는 것이 목적이다. 이 기록은 이용 허락이나 공정이용을 확인했다는 뜻이 아니다.
"""

import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from app.core.config import settings

KST = timezone(timedelta(hours=9))
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "collection_scope.toml"

# 출처 → 허용 목록 키.
#   naver_news       네이버 뉴스 검색. queries = 허용 검색어(종목명)
#   telegram_web     공개 채널 미리보기. channels = 허용 채널
#   telegram_link    공개 채널 메시지에 걸린 외부 기사를 여는 경로. 목록이 없다 — 어느 메시지의
#                    링크를 열지는 telegram_web 범위가 정한다. 발행처가 채널 운영자가 아니라서
#                    이용 조건을 따로 적으려고 출처를 나눴다
#   telegram_client  로그인 계정으로 받는 PDF. channels = 허용 채널
#   naver_research   네이버 증권 리서치. categories = 허용 API 분류, item_codes = company 리포트 종목
#   dart             DART 공시 목록. stock_codes = 허용 종목코드
SOURCES: dict[str, str | None] = {
    "naver_news": "queries",
    "telegram_web": "channels",
    "telegram_link": None,
    "telegram_client": "channels",
    "naver_research": "categories",
    "dart": "stock_codes",
}
TERMS_STATUSES = ("확인", "미확인", "미확정")
TERMS_KEYS = {"status", "basis", "checked_on", "open_issues"}


class ScopeError(RuntimeError):
    """범위 밖이거나 범위 파일이 잘못됐다. 수집을 시작하지 않는다."""


@dataclass(frozen=True)
class Terms:
    """출처 하나의 이용 조건 기록."""

    status: str  # 확인 | 미확인 | 미확정
    basis: str = ""  # 확인한 근거 (약관·이용 조건 문서 위치)
    checked_on: date | None = None  # 확인한 날짜
    open_issues: tuple[str, ...] = ()  # 미확정 사항


@dataclass(frozen=True)
class SourceScope:
    name: str
    enabled: bool = False
    allowed: frozenset[str] = frozenset()  # 검색어·채널·분류 (SOURCES 참고)
    item_codes: frozenset[str] = frozenset()  # naver_research company 리포트 종목
    max_items: int = 0
    terms: Terms | None = None

    def check(self, values: Iterable[str]) -> None:
        """허용 목록에 없는 값이 있으면 ScopeError."""
        outside = sorted(set(values) - self.allowed)
        if outside:
            raise ScopeError(
                f"{self.name}: 수집 범위에 없다: {', '.join(outside)}. "
                f"허용: {', '.join(sorted(self.allowed)) or '(없음)'} (collection_scope.toml)"
            )

    def remaining(self, collected: int) -> int:
        """이미 쌓인 행 수가 collected 일 때 더 받을 수 있는 수."""
        return max(self.max_items - collected, 0)


@dataclass(frozen=True)
class CollectionScope:
    start: date | None = None
    end: date | None = None
    sources: dict[str, SourceScope] = field(default_factory=dict)

    def source(self, name: str) -> SourceScope:
        return self.sources.get(name, SourceScope(name))

    def require(self, name: str) -> SourceScope:
        """켜진 출처만 돌려준다. 꺼져 있으면 ScopeError."""
        scope = self.source(name)
        if not scope.enabled:
            raise ScopeError(
                f"{name} 은(는) 수집 범위에서 꺼져 있다. 팀이 정한 범위를 "
                "ai/collection_scope.toml 에 적은 뒤 실행한다."
            )
        return scope

    def contains(self, day: date) -> bool:
        """자료 날짜가 기간 안인가."""
        return self.start is not None and self.end is not None and self.start <= day <= self.end

    def first_day(self, since: date) -> date | None:
        """since 부터 수집하려 할 때 실제로 받을 첫 날. 기간이 이미 끝났으면 None."""
        if self.start is None or self.end is None:
            return None
        first = max(since, self.start)
        return first if first <= self.end else None

    def window(self, since: datetime, until: datetime) -> tuple[datetime, datetime] | None:
        """[since, until] 을 기간에 맞게 자른 구간. 겹치지 않으면 None."""
        if self.start is None or self.end is None:
            return None
        lo = max(since, datetime.combine(self.start, time.min, KST))
        hi = min(until, datetime.combine(self.end, time.max, KST))
        return (lo, hi) if lo <= hi else None


def _date(value, where: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        raise ScopeError(f"{where}: 날짜만 적는다 (시각 없이 YYYY-MM-DD)")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ScopeError(f"{where}: 날짜가 아니다: {value!r} (YYYY-MM-DD)") from None


def _strings(value, where: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ScopeError(f"{where}: 빈칸 없는 문자열 목록이어야 한다")
    return frozenset(v.strip() for v in value)


def _terms(raw, where: str) -> Terms:
    if not isinstance(raw, dict):
        raise ScopeError(f"{where}: 표([...terms])로 적는다")
    unknown = set(raw) - TERMS_KEYS
    if unknown:
        raise ScopeError(f"{where}: 모르는 항목: {', '.join(sorted(unknown))}")
    status = raw.get("status")
    if status not in TERMS_STATUSES:
        raise ScopeError(f"{where}.status: {' | '.join(TERMS_STATUSES)} 중 하나")
    issues = raw.get("open_issues", [])
    return Terms(
        status=status,
        basis=str(raw.get("basis", "")).strip(),
        checked_on=_date(raw.get("checked_on"), f"{where}.checked_on"),
        open_issues=tuple(sorted(_strings(issues, f"{where}.open_issues"))) if issues else (),
    )


def _source(name: str, raw, period_set: bool) -> SourceScope:
    where = f"sources.{name}"
    if not isinstance(raw, dict):
        raise ScopeError(f"{where}: 표([{where}])로 적는다")
    list_key = SOURCES[name]
    known = {"enabled", "max_items", "terms"} | ({list_key} if list_key else set())
    if name == "naver_research":
        known.add("item_codes")
    unknown = set(raw) - known
    if unknown:
        raise ScopeError(f"{where}: 모르는 항목: {', '.join(sorted(unknown))}")

    enabled = raw.get("enabled", False)
    max_items = raw.get("max_items", 0)
    if not isinstance(enabled, bool) or not isinstance(max_items, int) or max_items < 0:
        raise ScopeError(f"{where}: enabled 는 true/false, max_items 는 0 이상의 정수")
    allowed = _strings(raw.get(list_key, []), f"{where}.{list_key}") if list_key else frozenset()
    item_codes = _strings(raw.get("item_codes", []), f"{where}.item_codes")
    terms = _terms(raw["terms"], f"{where}.terms") if "terms" in raw else None

    if enabled:
        # 켠 출처는 범위가 다 정해져 있어야 한다. 하나라도 비면 "아무거나" 가 되기 때문이다.
        missing = []
        if not period_set:
            missing.append("period.start·end")
        if max_items <= 0:
            missing.append("max_items")
        if list_key and not allowed:
            missing.append(list_key)
        if name == "naver_research" and "company" in allowed and not item_codes:
            missing.append("item_codes (company 를 켰으면 종목을 정한다)")
        if terms is None:
            missing.append("terms (이용 조건 기록. 미확인이어도 적는다)")
        if missing:
            raise ScopeError(f"{where} 을(를) 켰는데 정하지 않은 것이 있다: {', '.join(missing)}")
    return SourceScope(name=name, enabled=enabled, allowed=allowed, item_codes=item_codes,
                       max_items=max_items, terms=terms)


def parse_scope(raw: dict) -> CollectionScope:
    """TOML 을 읽은 dict → CollectionScope. 잘못 적었으면 ScopeError."""
    unknown = set(raw) - {"period", "sources"}
    if unknown:
        raise ScopeError(f"모르는 항목: {', '.join(sorted(unknown))}")
    period = raw.get("period", {})
    if not isinstance(period, dict) or set(period) - {"start", "end"}:
        raise ScopeError("period: start·end 만 적는다")
    start = _date(period.get("start"), "period.start")
    end = _date(period.get("end"), "period.end")
    if (start is None) != (end is None) or (start and end and start > end):
        raise ScopeError("period: start·end 를 함께 적고 start 가 end 보다 늦지 않아야 한다")

    sources_raw = raw.get("sources", {})
    if not isinstance(sources_raw, dict):
        raise ScopeError("sources: 출처별 표로 적는다")
    unknown = set(sources_raw) - set(SOURCES)
    if unknown:
        raise ScopeError(f"sources: 모르는 출처: {', '.join(sorted(unknown))}. "
                         f"있는 것: {', '.join(SOURCES)}")
    sources = {name: _source(name, value, start is not None) for name, value in sources_raw.items()}
    return CollectionScope(start=start, end=end, sources=sources)


def load_scope(path: Path | None = None) -> CollectionScope:
    """범위 파일을 읽는다. 파일이 없으면 ScopeError — 범위 없이 수집하지 않는다."""
    path = path or (Path(settings.collection_scope_file) if settings.collection_scope_file
                    else DEFAULT_PATH)
    if not path.exists():
        raise ScopeError(f"수집 범위 파일이 없다: {path}. 범위를 정하기 전에는 수집하지 않는다.")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ScopeError(f"{path.name} 을(를) 읽지 못했다: {exc}") from None
    return parse_scope(raw)
