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
"""

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal, create_tables
from app.repositories.analyst_report import known_ids, upsert_analyst_reports
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
    categories: tuple[str, ...] = CATEGORIES,
    with_pdf: bool = True,
    limit: int | None = None,
) -> dict[str, int]:
    """카테고리별 저장 건수. {'company': 118, 'industry': 46, ...}"""
    since = datetime.now(KST).date() - timedelta(days=days)
    await create_tables()

    saved: dict[str, int] = {}
    async with NaverResearchClient() as naver, SessionLocal() as session:
        for category in categories:
            seen = await known_ids(session, SOURCE, since, category)
            items = await naver.collect_since(category, since, known_ids=seen)
            if limit:
                items = items[:limit]
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
    return saved


def main() -> None:
    p = argparse.ArgumentParser(description="네이버 증권 리서치 수집")
    p.add_argument("--days", type=int, default=7, help="오늘로부터 며칠 전까지 (기본 7)")
    p.add_argument(
        "--category", action="append", choices=CATEGORIES,
        help="특정 카테고리만. 여러 번 줄 수 있다. 기본은 전부",
    )
    p.add_argument("--limit", type=int, help="카테고리당 최대 건수. 시험용")
    p.add_argument("--no-pdf", action="store_true", help="PDF 본문을 받지 않는다. 빠르다")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    saved = asyncio.run(
        collect(
            days=args.days,
            categories=tuple(args.category) if args.category else CATEGORIES,
            with_pdf=not args.no_pdf,
            limit=args.limit,
        )
    )
    for category, n in saved.items():
        print(f"  {category:10s} {n}건")
    print(f"합계 {sum(saved.values())}건")


if __name__ == "__main__":
    main()
