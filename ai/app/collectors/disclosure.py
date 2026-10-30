"""DART 공시 목록 → dart_disclosures 저장.

    uv run python -m app.collectors.disclosure                       # 오늘(KST)
    uv run python -m app.collectors.disclosure --date 2026-10-08
    uv run python -m app.collectors.disclosure --since 2026-10-06    # 그날부터 오늘까지 하루씩

뉴스·텔레그램에 종목 얘기가 없는 날에도 종목 고유의 재료를 찾으려고 받는다. 공시는 회사가
공식으로 낸 발표라 출처가 가장 확실하다. 목록만 받고 본문은 받지 않는다.

**하루치 코스피 공시를 받아 허용 종목만 남긴다**(services/dart/client.py). 허용 종목은
collection_scope.toml 의 dart.stock_codes 다. 수집 기간 밖의 날은 부르지도 않는다. 새 공시는
수집량 상한까지만 넣는다.

**장중에 여러 번 돌려도 된다.** 이미 있는 공시는 건너뛰므로 결과가 같다. 접수 시각을 API 가
주지 않아 처음 본 시각(first_seen_at)을 대신 남기는데, 자주 돌릴수록 실제 시각에 가까워진다.

새 공시는 저장을 커밋한 뒤 공통 자료 ID(source_card)에 등록한다. 등록이 실패해도 공시는 남고,
`uv run python -m app.collectors.sources register` 로 다시 등록하면 된다.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.core.database import SessionLocal
from app.core.scope import KST, CollectionScope, ScopeError, SourceScope, load_scope
from app.repositories.dart_disclosure import known_rcept_nos, save_disclosures
from app.repositories.scope import collection_locks, count_collected
from app.repositories.source_card import register_missing_sources
from app.services.dart import client as dart
from app.services.dart.client import DartError
from app.services.dart.schema import Disclosure

# 실패 종류(services/news/failure.py)별로 다시 돌려도 되는지 알려 준다. 자동 재시도는 하지 않는다.
FAILURE_HINTS = {
    "permanent": "다시 돌려도 같은 결과다. DART_API_KEY·접근 IP·요청 값을 확인한다.",
    "rate_limited": "DART 요청 한도를 넘었다. 한도가 풀린 뒤 다시 돌린다.",
    "unknown": "일시 실패일 수 있다. 잠시 뒤 다시 돌린다.",
}


@dataclass
class CollectResult:
    fetched: int = 0  # 그날 코스피 공시 전체
    matched: int = 0  # 그중 허용 종목
    held: int = 0  # 수집량 상한 때문에 넣지 않은 새 공시
    inserted: int = 0
    out_of_period: bool = False  # 날짜가 수집 기간 밖이라 부르지 않았다
    cards: dict[str, int] = field(default_factory=dict)  # 새로 만든 공통 자료 ID 수
    register_error: str | None = None  # 공시는 저장했지만 공통 자료 ID 등록에 실패한 사유


def select_items(
    items: list[Disclosure],
    *,
    source: SourceScope,
    known: set[str],
    collected: int,
    result: CollectResult,
) -> list[Disclosure]:
    """허용 종목의 새 공시만 상한 안에서 남긴다. 같은 접수번호가 두 번 오면 한 번만 센다."""
    budget = source.remaining(collected)
    kept: list[Disclosure] = []
    for item in items:
        if item.stock_code not in source.allowed:
            continue
        result.matched += 1
        if item.rcept_no in known:
            continue
        if budget <= 0:
            result.held += 1
            continue
        budget -= 1
        known.add(item.rcept_no)
        kept.append(item)
    return kept


async def collect(day: date, *, scope: CollectionScope | None = None) -> CollectResult:
    """범위 밖이면 ScopeError. 날짜가 기간 밖이면 DART 를 부르지 않고 빈 결과."""
    scope = scope or load_scope()
    source = scope.require("dart")
    if not scope.contains(day):
        return CollectResult(out_of_period=True)
    async with collection_locks(SessionLocal, "dart"):
        items = await dart.fetch_day(day)
        result = CollectResult(fetched=len(items))
        async with SessionLocal() as session:
            known = await known_rcept_nos(session, [i.rcept_no for i in items])
            collected = await count_collected(session, "dart")
            kept = select_items(items, source=source, known=known, collected=collected,
                                result=result)
            saved_ids = await save_disclosures(session, kept)
            await session.commit()
        result.inserted = len(saved_ids)
        try:
            async with SessionLocal() as session:
                result.cards = await register_missing_sources(
                    session, news_ids=[], report_ids=[], message_ids=[],
                    disclosure_ids=saved_ids,
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            result.register_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result


def _days(since: date, until: date) -> list[date]:
    return [since + timedelta(days=n) for n in range((until - since).days + 1)]


async def _collect_days(days: list[date]) -> None:
    """한 이벤트 루프에서 하루씩. 날마다 asyncio.run 하면 DB 연결 풀이 다른 루프에 묶인다."""
    scope = load_scope()
    for day in days:
        result = await collect(day, scope=scope)
        if result.out_of_period:
            print(f"{day}: 수집 기간 밖이라 받지 않음")
            continue
        line = (f"{day}: 코스피 공시 {result.fetched}건 / 허용 종목 {result.matched}건 / "
                f"새로 저장 {result.inserted}건")
        if result.held:
            line += f" / 수집량 상한으로 받지 않음 {result.held}건"
        print(line)
        if result.register_error:
            print(f"  공통 자료 ID 등록 실패 ({result.register_error}) — "
                  "`uv run python -m app.collectors.sources register` 로 다시 등록한다")


def main() -> None:
    p = argparse.ArgumentParser(description="DART 공시 목록을 dart_disclosures 에 저장")
    p.add_argument("--date", type=date.fromisoformat, help="이날 하루. 기본은 오늘(KST)")
    p.add_argument("--since", type=date.fromisoformat, help="이날부터 오늘까지 하루씩")
    args = p.parse_args()
    if args.date and args.since:
        p.error("--date 와 --since 중 하나만 준다")

    today = datetime.now(KST).date()
    days = _days(args.since, today) if args.since else [args.date or today]
    try:
        asyncio.run(_collect_days(days))
    except ScopeError as exc:
        p.exit(1, f"{exc}\n")
    except DartError as exc:
        p.exit(1, f"공시 수집 실패: {exc}\n  {FAILURE_HINTS.get(exc.kind, FAILURE_HINTS['unknown'])}\n")
    except RuntimeError as exc:
        p.exit(1, f"공시 수집 실패: {exc}\n")


if __name__ == "__main__":
    main()
