"""보고서 스크랩. 스크랩 행에 보고서 요약을 붙여 마이페이지 카드로 만든다."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.mvp_stocks import MVP_CODES
from app.repositories import report_scrap as scrap_repo
from app.repositories.stock_report import ReportStoreUnavailable, StockReportRepository
from app.schemas.report_scrap import MyScrap, MyScrapList
from app.services.stock_report import headline, source_channels, to_report


async def list_my_scraps(
    session: AsyncSession, reports: StockReportRepository, user_id: int
) -> MyScrapList:
    scraps = await scrap_repo.list_for_user(session, user_id)
    try:
        rows = await reports.get_many([scrap.report_id for scrap in scraps])
    except ReportStoreUnavailable:
        rows = []
    by_id = {row.id: row for row in rows}
    items = []
    for scrap in scraps:
        row = by_id.get(scrap.report_id)
        report = to_report(row) if row else None
        if row is None or report is None or report.code not in MVP_CODES:
            # 보고서가 지워졌거나, 본문을 읽을 수 없거나, 서비스 종목에서 빠졌다.
            # 목록에서 빼지 않고 "찾을 수 없음" 카드로 내려 사용자가 알 수 있게 한다.
            # 스크랩 행에는 종목 정보가 없어 카드를 채울 수 없다.
            items.append(
                MyScrap(
                    scrap_id=str(scrap.id),
                    report_id=scrap.report_id,
                    available=False,
                    scrapped_at=scrap.created_at,
                )
            )
            continue
        items.append(
            MyScrap(
                scrap_id=str(scrap.id),
                report_id=report.id,
                stock_code=report.code,
                stock_name=report.name,
                change_pct=report.change_pct,
                as_of=report.as_of,
                target_date=row.target_date,
                headline=headline(report),
                generated_at=report.generated_at,
                sources=source_channels(report),
                scrapped_at=scrap.created_at,
            )
        )
    return MyScrapList(items=items)


async def add_scrap(
    session: AsyncSession, reports: StockReportRepository, user_id: int, report_id: int
) -> None:
    try:
        exists = bool(await reports.get_many([report_id]))
    except ReportStoreUnavailable:
        exists = False
    if not exists:
        raise AppError("REPORT_NOT_FOUND", "보고서를 찾을 수 없습니다", 404)
    await scrap_repo.add(session, user_id, report_id)
