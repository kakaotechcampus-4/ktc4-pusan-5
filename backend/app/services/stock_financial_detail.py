from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import StockCollectionJob, StockCollectionState
from app.repositories.stock import enqueue, touch
from app.repositories.stock_financials import list_periods
from app.schemas.stock import Resource
from app.schemas.stock_financials import (
    AnnualEps,
    AnnualIncome,
    AnnualStability,
    FinancialHealth,
    StockFinancials,
)
from app.services.stock_detail import require_stock

FINANCIAL_TTL = 86400


async def financials(session: AsyncSession, code: str) -> StockFinancials:
    stock = await require_stock(session, code)
    now = datetime.now(UTC)
    sections = {}
    definitions = (
        ("income", AnnualIncome, ("revenue", "operating_profit", "net_income")),
        ("eps", AnnualEps, ("eps", "roe", "debt_ratio")),
        ("stability", AnnualStability, ("current_ratio",)),
    )
    for kind, schema, fields in definitions:
        state = await session.get(StockCollectionState, (code, kind))
        records = await list_periods(session, code, kind)
        data = []
        for row in reversed(records):
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
    response = StockFinancials(
        code=code, income=sections["income"], eps=sections["eps"], health=health_summary(sections)
    )
    await session.commit()
    return response


def health_summary(sections: dict[str, Resource]) -> Resource[FinancialHealth]:
    """동일 결산월만 결합한다. 공통 기간이 없으면 최신 기간의 존재하는 값만 제공한다."""
    indexed = {
        kind: {row.fiscal_period: row for row in (section.data or [])}
        for kind, section in sections.items()
    }
    available = [set(rows) for rows in indexed.values() if rows]
    resources = list(sections.values())
    refreshing = any(section.refreshing for section in resources)
    retries = [
        section.retry_after_seconds
        for section in resources
        if section.retry_after_seconds is not None
    ]
    retry = min(retries) if retries else None
    data = None
    collected = None
    if available:
        common = set.intersection(*available)
        period = max(common or set.union(*available))
        income = indexed["income"].get(period)
        eps = indexed["eps"].get(period)
        stability = indexed["stability"].get(period)
        margin = None
        if income and income.revenue not in (None, 0) and income.operating_profit is not None:
            margin = income.operating_profit / income.revenue * 100
        data = FinancialHealth(
            fiscal_period=period,
            debt_ratio=eps.debt_ratio if eps else None,
            roe=eps.roe if eps else None,
            operating_margin=margin,
            current_ratio=stability.current_ratio if stability else None,
        )
        timestamps = [
            sections[kind].collected_at
            for kind, rows in indexed.items()
            if period in rows and sections[kind].collected_at
        ]
        collected = min(timestamps) if timestamps else None
        delayed = any(section.status in ("stale", "unavailable") for section in resources)
        period_mismatch = any(
            period not in rows or max(rows) != period for rows in indexed.values() if rows
        )
        status = "stale" if delayed or period_mismatch else "ready"
    elif any(section.status == "pending" for section in resources):
        status = "pending"
    elif any(section.status == "unavailable" for section in resources):
        status = "unavailable"
    else:
        status = "empty"
    return Resource(
        status=status,
        data=data,
        refreshing=refreshing,
        collected_at=collected,
        retry_after_seconds=retry,
    )
