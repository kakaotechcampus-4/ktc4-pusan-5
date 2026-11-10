from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import get_current_user
from app.models import User
from app.repositories import report_scrap as scrap_repo
from app.repositories.stock_report import StockReportRepository
from app.routers.stocks import get_report_repository
from app.schemas.report_scrap import MyScrapList
from app.schemas.stock_report import ReportList
from app.services import report_scrap, stock_report

router = APIRouter(prefix="/api", tags=["reports"])
ReportId = Annotated[int, Path(ge=1)]


@router.get("/reports", response_model=ReportList)
async def list_reports(
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
    repository: StockReportRepository = Depends(get_report_repository),
):
    """종목마다 가장 최근 보고서 하나씩, 최근 순. 홈의 보고서 목록에 쓴다."""
    return await stock_report.list_reports(repository, limit)


@router.get("/scraps", response_model=MyScrapList)
async def list_scraps(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    repository: StockReportRepository = Depends(get_report_repository),
):
    return await report_scrap.list_my_scraps(session, repository, user.id)


@router.put("/scraps/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_scrap(
    report_id: ReportId,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    repository: StockReportRepository = Depends(get_report_repository),
) -> Response:
    """이미 스크랩한 보고서를 다시 눌러도 성공한다. 없는 보고서면 404 REPORT_NOT_FOUND."""
    await report_scrap.add_scrap(session, repository, user.id, report_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/scraps/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_scrap(
    report_id: ReportId,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await scrap_repo.remove(session, user.id, report_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
