"""증권사 리포트 수집 → 정규화 → DB 저장.

    uv run python -m app.collectors.analyst_report --days 7
    uv run python -m app.collectors.analyst_report --days 1 --category company
    uv run python -m app.collectors.analyst_report --days 1 --limit 5 --no-pdf   # 빠른 확인용

도는 순서:
    ① 카테고리별 목록을 since 이후까지 넘긴다 (호출 1~2회)
    ② 이미 DB 에 있는 researchId 는 건너뛴다 — 증분의 핵심
    ③ 남은 것만 상세 + PDF 본문을 받는다 (항목당 2회)
    ④ upsert 한다. 카테고리 단위로 커밋해서 중간에 끊겨도 앞은 남는다

목표주가·투자의견은 PDF 에서 뽑지 않는다. 네이버가 준 값만 쓴다.
PDF 는 텍스트만 남기고 파일은 버린다(services/analyst/naver.py 참고).

지금은 --days 로 직접 돌린다. 나중에 스케줄러가 하루 1~2회 돌리게 할 예정이다.
리포트는 장 전후로 올라오지 실시간으로 쏟아지는 게 아니라 그 정도면 충분하다.

**수집 범위 안에서만 받는다**(collection_scope.toml 의 naver_research). 허용한 분류만 받고,
company 리포트는 허용한 종목만 받는다. 작성일이 기간 밖이면 받지 않고, 새 리포트는 수집량
상한까지만 상세·PDF 를 받는다.
"""

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.core.scope import CollectionScope, ScopeError, load_scope
from app.repositories.analyst_report import known_ids, upsert_analyst_reports
from app.repositories.scope import collection_locks, count_collected
from app.repositories.source_card import register_missing_sources
from app.services.analyst.naver import CATEGORIES, NaverResearchClient, utcnow
from app.services.analyst.schema import AnalystReportItem, PdfText

logger = logging.getLogger(__name__)
SOURCE = "naver"
# 리포트 발행일(writeDate)은 한국 장 기준이다. 서버가 UTC 면 date.today() 가
# 한국 날짜보다 하루 뒤처져서 당일 리포트를 통째로 놓친다. 그래서 KST 로 고정한다.
KST = timezone(timedelta(hours=9))


def _to_row(item: AnalystReportItem, pdf: PdfText | None) -> dict:
    body = pdf or PdfText(status="pending")
    return {
        "source": SOURCE,
        "source_id": item.source_id,
        "source_category": item.source_category,
        "category": item.category,
        "item_code": item.item_code,
        "item_name": item.item_name,
        "broker": item.broker,
        "title": item.title,
        "write_date": item.write_date,
        "read_count": item.read_count,
        "opinion": item.opinion,
        "goal_price": item.goal_price,
        "price_at_write": item.price_at_write,
        "upside_pct": item.upside_pct,
        "sector_opinion": item.sector_opinion,
        "top_picks": item.top_picks or None,
        "summary_html": item.summary_html,
        "summary_text": item.summary_text,
        "summary_chars": len(item.summary_text) if item.summary_text else None,
        "end_url": item.end_url,
        "attach_url": item.attach_url,
        "pdf_sha256": body.sha256,
        "pdf_bytes": body.size_bytes,
        "pdf_pages": body.pages,
        "body_text": body.text,
        "body_chars": body.chars or None,
        "body_status": body.status,
        "body_extractor": body.extractor,
        "body_error": body.error,
        "body_fetched_at": utcnow() if pdf else None,
    }


async def collect(
    *,
    days: int = 7,
    categories: tuple[str, ...] | None = None,
    with_pdf: bool = True,
    limit: int | None = None,
    scope: CollectionScope | None = None,
) -> dict[str, int]:
    """카테고리별 저장 건수. {'company': 118, 'industry': 46, ...}

    categories 를 주지 않으면 수집 범위의 분류 전부다. 범위 밖이면 ScopeError.
    """
    scope = scope or load_scope()
    source = scope.require("naver_research")
    unknown = sorted(source.allowed - set(CATEGORIES))
    if unknown:
        raise ScopeError(f"naver_research: 네이버에 없는 분류: {', '.join(unknown)}. "
                         f"있는 것: {', '.join(CATEGORIES)}")
    categories = categories or tuple(sorted(source.allowed))
    source.check(categories)
    since = scope.first_day(datetime.now(KST).date() - timedelta(days=days))
    if since is None:
        raise ScopeError(f"수집 기간({scope.start}~{scope.end}) 밖이다. 받을 리포트가 없다.")

    saved: dict[str, int] = {}
    report_keys: list[tuple[str, str, str]] = []
    async with (
        collection_locks(SessionLocal, "naver_research"),
        NaverResearchClient() as naver,
        SessionLocal() as session,
    ):
        for category in categories:
            seen = await known_ids(session, SOURCE, since, category)
            items = await naver.collect_since(category, since, known_ids=seen)
            items = [i for i in items if scope.contains(i.write_date)]
            if category == "company":
                items = [i for i in items if i.item_code in source.item_codes]
            if limit:
                items = items[:limit]
            budget = source.remaining(await count_collected(session, "naver_research"))
            if len(items) > budget:
                logger.info("%s: 수집량 상한으로 %d건은 받지 않는다", category, len(items) - budget)
                items = items[:budget]
            if not items:
                logger.info("%s: 새 리포트 없음 (기존 %d건)", category, len(seen))
                saved[category] = 0
                continue

            logger.info("%s: 새 리포트 %d건 — 상세+PDF 받는다", category, len(items))
            enriched = await naver.enrich(items, with_pdf=with_pdf)
            saved[category] = await upsert_analyst_reports(
                session, [_to_row(i, p) for i, p in enriched]
            )
            await session.commit()  # 카테고리 단위 커밋. 중간에 끊겨도 앞은 남는다
            report_keys.extend((SOURCE, i.source_category, i.source_id) for i, _ in enriched)

        # 공통 자료 ID 는 리포트를 다 커밋한 뒤 따로 등록한다. 실패해도 리포트는 남는다.
        try:
            cards = await register_missing_sources(
                session, news_ids=[], message_ids=[], report_keys=report_keys,
            )
            await session.commit()
        except Exception as exc:
            raise RuntimeError(
                f"리포트는 저장했지만 공통 자료 ID 등록에 실패했다 ({type(exc).__name__}). "
                "`uv run python -m app.collectors.sources register` 로 다시 등록한다."
            ) from exc
        logger.info("공통 자료 ID 새로 %s", cards)
    return saved


def main() -> None:
    p = argparse.ArgumentParser(description="네이버 증권 리서치 수집")
    p.add_argument("--days", type=int, default=7, help="오늘로부터 며칠 전까지 (기본 7)")
    p.add_argument(
        "--category", action="append", choices=CATEGORIES,
        help="특정 카테고리만. 여러 번 줄 수 있다. 기본은 수집 범위의 분류 전부",
    )
    p.add_argument("--limit", type=int, help="카테고리당 최대 건수. 시험용")
    p.add_argument("--no-pdf", action="store_true", help="PDF 본문을 받지 않는다. 빠르다")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        saved = asyncio.run(
            collect(
                days=args.days,
                categories=tuple(args.category) if args.category else None,
                with_pdf=not args.no_pdf,
                limit=args.limit,
            )
        )
    except ScopeError as exc:
        p.exit(1, f"{exc}\n")
    for category, n in saved.items():
        print(f"  {category:10s} {n}건")
    print(f"합계 {sum(saved.values())}건")


if __name__ == "__main__":
    main()
