from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import StockCollectionJob, StockCollectionState
from app.repositories.stock import enqueue, touch
from app.repositories.stock_financials import list_periods
from app.schemas.stock import Resource
from app.schemas.stock_financials import AnnualEps, AnnualIncome, StockFinancials
from app.services.stock_detail import require_stock

FINANCIAL_TTL = 86400


async def financials(session: AsyncSession, code: str) -> StockFinancials:
    stock = await require_stock(session, code)
    now = datetime.now(UTC)
    sections = {}
    for kind, schema in (("income", AnnualIncome), ("eps", AnnualEps)):
        state = await session.get(StockCollectionState, (code, kind))
        records = await list_periods(session, code, kind)
        data = []
        for row in reversed(records):
            fields = ("revenue", "operating_profit", "net_income") if kind == "income" else ("eps",)
            data.append(
                schema(
                    fiscal_period=row.period_end.strftime("%Y-%m"),
                    **{field: getattr(row, field) for field in fields},
                )
            )
        expired = (
            not state
            or not state.last_success_at
            or (now - state.last_success_at).total_seconds() >= FINANCIAL_TTL
        )
        await touch(session, code, kind, now)
        if expired and stock.listing_status == "listed":
            await enqueue(session, code, kind, now, priority=5)
        job = await session.scalar(
            select(StockCollectionJob).where(
                StockCollectionJob.stock_code == code, StockCollectionJob.resource == kind
            )
        )
        refreshing = bool(
            job and job.status in ("queued", "running") and stock.listing_status == "listed"
        )
        error = state.error_code if state else None
        if data:
            status = "stale" if expired or error else "ready"
        elif error:
            status = "unavailable"
        elif state and state.last_success_at:
            status = "empty"
        else:
            status = "pending" if stock.listing_status == "listed" else "unavailable"
        retry = (
            max(3, int((state.next_retry_at - now).total_seconds()))
            if state and state.next_retry_at and state.next_retry_at > now
            else 3
        )
        sections[kind] = Resource(
            status=status,
            refreshing=refreshing,
            data=data if data or status == "empty" else None,
            collected_at=state.last_success_at if state else None,
            retry_after_seconds=retry
            if stock.listing_status == "listed" and (refreshing or error or status == "pending")
            else None,
        )
    response = StockFinancials(code=code, **sections)
    await session.commit()
    return response
