"""네이버 뉴스 검색 → 본문 추출 → news 저장 → 공통 자료 ID 등록.

    uv run python -m app.collectors.news 삼성전자
    uv run python -m app.collectors.news 삼성전자 --display 50
    uv run python -m app.collectors.news --retry-failed                  # 본문을 못 얻은 기사만 다시 연다
    uv run python -m app.collectors.news --retry-failed --max-age-hours 72

backend `app/collectors/news.py` 에서 옮겨 왔다. 검색과 본문 추출(trafilatura)은 그대로다.
저장이 달라졌다(repositories/news.py).
    - 같은 기사가 이미 있으면 건너뛰지 않고, 비어 있던 본문·발행 시각·제목·요약만 채운다
    - 한 번 확보한 본문은 덮어쓰지 않는다
    - 본문 상태·실패 사유·받은 시각을 같이 남긴다

**재시도는 발행 24시간 이내 기사만 한다(기본).** 기사는 발행 뒤에도 고쳐진다. 오래 지나 받은
본문은 보고서 기준 시각 이후의 수정을 담고 있을 수 있다. 받은 시각(body_fetched_at)이 남으니
걸러낼 수는 있지만, 굳이 그런 본문을 만들지 않는다. 텔레그램 링크 수집기와 같은 기준이다.

**수집 범위 안에서만 받는다**(collection_scope.toml 의 naver_news). 검색어는 허용 목록에 있어야
하고, 발행일이 기간 밖인 기사는 받지 않는다. 새 기사는 수집량 상한까지만 받고, 상한을 넘는
기사는 본문을 열지도 않는다. 이미 있는 기사는 상한과 상관없이 비어 있던 것을 채운다.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.core.database import SessionLocal
from app.core.scope import KST, CollectionScope, ScopeError, SourceScope, load_scope
from app.repositories.news import failed_news, known_news_keys, save_news
from app.repositories.scope import count_collected
from app.repositories.source_card import register_missing_sources
from app.services.news import naver
from app.services.news.content import attach_bodies
from app.services.news.schema import NewsItem
from app.services.news.url import canonical_url

DEFAULT_DISPLAY = 20
# 재시도할 기사의 최대 나이(발행 기준, 모르면 수집 기준). 맨 위 설명 참고.
DEFAULT_RETRY_MAX_AGE = timedelta(hours=24)
DEFAULT_RETRY_LIMIT = 200


def _to_row(item: NewsItem) -> dict:
    """news 행. 정제 결과가 비면 본문을 얻지 못한 것으로 친다."""
    ok = bool(item.cleaned_text)
    return {
        "url": str(item.url),
        "title": item.title,
        "publisher": item.publisher,
        "source": item.source,
        "published_at": item.published_at,
        "summary": item.summary,
        "cleaned_text": item.cleaned_text if ok else None,
        "body_status": "ok" if ok else "failed",
        "body_error": None if ok else (item.body_error or "clean_empty"),
        "body_fetched_at": item.body_fetched_at,
        "body_extractor": "trafilatura",
    }


@dataclass
class CollectResult:
    fetched: int = 0  # 검색 결과(또는 재시도 대상) 건수
    out_of_period: int = 0  # 발행일이 수집 기간 밖이라 받지 않은 기사
    held: int = 0  # 수집량 상한 때문에 받지 않은 새 기사
    inserted: int = 0  # 새 기사
    filled: int = 0  # 실패했던 본문을 이번에 채운 기사
    cards: dict[str, int] = field(default_factory=dict)
    register_error: str | None = None  # 공통 자료 ID 등록 실패. 기사는 저장됐다


def select_items(
    items: list[NewsItem],
    *,
    scope: CollectionScope,
    source: SourceScope,
    known: set[str],
    collected: int,
    result: CollectResult,
) -> list[NewsItem]:
    """범위 안의 기사만 남긴다. 이미 있는 기사(known: 정규화 주소)는 상한과 상관없이 남긴다."""
    budget = source.remaining(collected)
    kept: list[NewsItem] = []
    for item in items:
        if not scope.contains(item.published_at.astimezone(KST).date()):
            result.out_of_period += 1
            continue
        key = canonical_url(str(item.url))
        if key not in known:
            if budget <= 0:
                result.held += 1
                continue
            budget -= 1
            known.add(key)  # 같은 검색 결과에 같은 기사가 또 있으면 한 번만 센다
        kept.append(item)
    return kept


async def _known_and_collected(items: list[NewsItem]) -> tuple[set[str], int]:
    async with SessionLocal() as session:
        known = await known_news_keys(session, [str(item.url) for item in items])
        return known, await count_collected(session, "naver_news")


async def _save(items: list[NewsItem], result: CollectResult) -> CollectResult:
    async with SessionLocal() as session:
        saved = await save_news(session, [_to_row(i) for i in items])
        await session.commit()
    result.inserted, result.filled = saved.inserted, saved.filled
    # 등록은 기사를 커밋한 뒤 따로 한다. 실패해도 기사는 남고 다시 등록하면 된다.
    try:
        async with SessionLocal() as session:
            result.cards = await register_missing_sources(session)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        result.register_error = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result


async def collect(
    query: str, *, display: int = DEFAULT_DISPLAY, scope: CollectionScope | None = None
) -> CollectResult:
    """범위 밖이면 ScopeError. 검색은 범위를 확인한 뒤에만 한다."""
    scope = scope or load_scope()
    source = scope.require("naver_news")
    source.check([query])
    items = await naver.search(query, display=display)
    result = CollectResult(fetched=len(items))
    known, collected = await _known_and_collected(items)
    items = select_items(items, scope=scope, source=source, known=known, collected=collected,
                         result=result)
    items = await attach_bodies(items)
    # 여기가 나중에 분류(feature/data-classification)가 들어갈 자리. 원문 저장과는 따로 돈다.
    return await _save(items, result)


async def retry_failed(
    *,
    max_age: timedelta = DEFAULT_RETRY_MAX_AGE,
    limit: int = DEFAULT_RETRY_LIMIT,
    scope: CollectionScope | None = None,
) -> CollectResult:
    """본문을 못 얻은 네이버 기사의 원문을 다시 연다. 얻으면 채우고, 또 실패하면 사유만 바꾼다.

    이미 있는 기사라 수집량 상한은 늘지 않는다. 출처가 꺼졌거나 발행일이 기간 밖이면 열지 않는다.
    """
    scope = scope or load_scope()
    scope.require("naver_news")
    since = datetime.now(UTC) - max_age
    async with SessionLocal() as session:
        targets = await failed_news(session, source="naver", since=since, limit=limit)
    items = [
        NewsItem(title=n.title, url=n.url, publisher=n.publisher, published_at=n.published_at,
                 source="naver", summary=n.summary)
        for n in targets
        # 네이버 행은 발행 시각이 있다
        if n.published_at is not None and scope.contains(n.published_at.astimezone(KST).date())
    ]
    if not items:
        return CollectResult()
    items = await attach_bodies(items)
    return await _save(items, CollectResult(fetched=len(items)))


def main() -> None:
    p = argparse.ArgumentParser(description="네이버 뉴스 검색 결과와 본문을 news 에 저장")
    p.add_argument("query", nargs="?", help="검색어. 보통 종목명")
    p.add_argument("--display", type=int, default=DEFAULT_DISPLAY)
    p.add_argument("--retry-failed", action="store_true",
                   help="검색하지 않고, 본문을 못 얻은 기사만 다시 연다")
    p.add_argument("--max-age-hours", type=float,
                   default=DEFAULT_RETRY_MAX_AGE.total_seconds() / 3600,
                   help="--retry-failed 대상의 최대 나이(시간, 발행 기준). 기본 24")
    args = p.parse_args()
    if args.retry_failed == bool(args.query):
        p.error("검색어 또는 --retry-failed 중 하나만 준다")

    try:
        if args.retry_failed:
            result = asyncio.run(retry_failed(max_age=timedelta(hours=args.max_age_hours)))
            print(f"재시도 {result.fetched}건 / 본문 보완 {result.filled}건")
        else:
            result = asyncio.run(collect(args.query, display=args.display))
            print(f"가져온 {result.fetched}건 / 새로 저장 {result.inserted}건 / "
                  f"본문 보완 {result.filled}건")
    except ScopeError as exc:
        p.exit(1, f"{exc}\n")
    if result.out_of_period or result.held:
        print(f"범위: 발행일이 기간 밖 {result.out_of_period}건 · 수집량 상한으로 받지 않음 "
              f"{result.held}건")
    if result.register_error:
        p.exit(1, f"공통 자료 ID 등록 실패: {result.register_error}\n"
                  "  기사는 저장됐다. `uv run python -m app.collectors.sources register` 로 다시 등록한다.\n")
    if result.cards:
        print("공통 자료 ID 새로 " + " · ".join(f"{k} {n}" for k, n in result.cards.items()))


if __name__ == "__main__":
    main()
