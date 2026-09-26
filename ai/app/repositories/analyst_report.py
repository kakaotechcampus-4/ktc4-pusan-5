from datetime import date

from sqlalchemy import case, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalystReport


async def known_ids(
    session: AsyncSession, source: str, since: date, source_category: str
) -> set[str]:
    """since 이후로 이미 받아둔 리포트 ID.

    목록은 한 번에 100건씩 오지만 상세·PDF 는 건당 2회 호출이다. 이미 있는 걸 먼저
    걸러내지 않으면 매일 같은 리포트를 수백 번 다시 받는다. 증분 수집의 핵심이다.

    **category 가 아니라 source_category 로 거른다.** 목록을 받아온 단위가 그거라서다.
    네이버는 카테고리별로 목록을 따로 받고 텔레그램은 채널별로 훑는다. category 로
    거르면 invest·daily 가 둘 다 market 이라 목록 단위와 안 맞아서 이미 받아둔 걸
    못 찾는다. 텔레그램 PDF 는 건당 평균 3.7MB 라 한 번 놓치면 1.4GB 를 다시 받는다.
    """
    stmt = select(AnalystReport.source_id).where(
        AnalystReport.source == source,
        AnalystReport.source_category == source_category,
    )
    # 텔레그램은 오래된 발행일의 PDF도 오늘 다시 게시할 수 있다.
    # 조회 기간은 메시지 게시일에 적용하고, 받은 메시지 번호는 전 기간에서 찾는다.
    if source != "telegram":
        stmt = stmt.where(AnalystReport.write_date >= since)
    rows = await session.execute(stmt)
    return set(rows.scalars().all())


async def known_naver_pdf_hashes(session: AsyncSession) -> set[str]:
    """파일명이 달라도 PDF 바이트가 같으면 네이버 수집본으로 판단한다."""
    result = await session.execute(select(AnalystReport.pdf_sha256).where(
        AnalystReport.source == "naver", AnalystReport.pdf_sha256.is_not(None),
        AnalystReport.pdf_sha256 != "",
    ).distinct())
    return set(result.scalars().all())


async def upsert_analyst_reports(session: AsyncSession, rows: list[dict]) -> int:
    """(source, source_category, source_id) 가 자연키다. 같은 기간을 다시 돌려도 중복이 안 생긴다.

    **category 가 아니라 source_category 다.** category 는 우리가 정하는 값이라 바뀔 수 있다.

    텔레그램의 기존 메시지는 보존하고, 네이버는 조회 수와 제공 요약을 갱신한다.
    네이버 PDF 재수집에 실패해도 기존 정상 본문과 PDF 정보를 보존한다.

    네이버에 같은 PDF가 있으면 텔레그램 행은 저장하지 않는다.
    반환값은 실제 삽입/갱신한 행 수이며 중복으로 건너뛴 행은 제외한다.
    """
    if not rows:
        return 0
    # 같은 PDF의 네이버 저장이 먼저 시작됐다면 완료 후 중복 여부를 확인한다.
    # 여러 PDF를 처리할 때는 동일한 잠금 순서로 교착을 피한다.
    for sha in sorted({r["pdf_sha256"] for r in rows if r.get("pdf_sha256")}):
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:sha, 0))"),
                              {"sha": sha})
    # 텔레그램 수집은 신규 메시지만 추가한다. 본문 재추출/요약 교정은 별도 작업이다.
    # 중복 조회와 INSERT 사이의 동시 수집도 기존 원문·요약·교정값을 건드리지 않는다.
    telegram = [row for row in rows if row["source"] == "telegram"]
    others = [row for row in rows if row["source"] != "telegram"]
    saved = 0
    if telegram:
        naver_hashes = await known_naver_pdf_hashes(session)
        naver_hashes.update(r["pdf_sha256"] for r in others
                            if r["source"] == "naver" and r.get("pdf_sha256"))
        telegram = [r for r in telegram
                    if not r.get("pdf_sha256") or r["pdf_sha256"] not in naver_hashes]
    if telegram:
        result = await session.execute(insert(AnalystReport).values(telegram).on_conflict_do_nothing(
            constraint="uq_analyst_report_source_id",
        ).returning(AnalystReport.id))
        saved += len(result.scalars().all())
    if others:
        stmt = insert(AnalystReport).values(others)
        updatable = [c for c in others[0] if c not in (
            "source", "source_category", "source_id", "collected_at",
        )]
        pdf_fields = {
            "attach_url", "pdf_sha256", "pdf_bytes", "pdf_pages", "body_text", "body_chars",
            "body_status", "body_extractor", "body_error", "body_fetched_at",
        }
        preserve_pdf = (AnalystReport.body_status == "ok") & (
            stmt.excluded.body_status.in_(("pending", "failed", "empty", "skipped", "unusable"))
        )
        updates = {
            c: case((preserve_pdf, getattr(AnalystReport, c)),
                    else_=getattr(stmt.excluded, c)) if c in pdf_fields
            else getattr(stmt.excluded, c)
            for c in updatable
        }
        result = await session.execute(stmt.on_conflict_do_update(
            constraint="uq_analyst_report_source_id", set_=updates,
        ).returning(AnalystReport.id))
        saved += len(result.scalars().all())
    return saved
