import calendar
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.models.stock import Stock, StockCollectionJob
from app.repositories.stock import enqueue
from app.repositories.stock_history import HISTORY_TTL, history_for


async def enrich_history(session, code, investment):
    if not investment.data:
        return investment
    stock = await session.get(Stock, code)
    listed = stock.listing_status == "listed"
    now = datetime.now(UTC)
    saved = await history_for(session, code)
    jobs = {
        (job.resource, job.range_start): job
        for job in (
            await session.scalars(
                select(StockCollectionJob).where(
                    StockCollectionJob.stock_code == code,
                    StockCollectionJob.resource.in_(["history_cap", "history_rs"]),
                )
            )
        ).all()
    }
    pending = False
    failure = False
    retries = []
    for point in investment.data:
        year, month = map(int, point.fiscal_period.split("-"))
        period = date(year, month, calendar.monthrange(year, month)[1])
        row = saved.get(period)
        if row:
            point.market_cap = float(row.market_cap) if row.market_cap is not None else None
            point.market_cap_as_of = row.cap_as_of
            point.rs = float(row.rs) if row.rs is not None else None
            point.rs_as_of = row.rs_as_of
            point.rs_base_date = row.rs_base_date
        for kind, attr in (("history_cap", "cap_collected_at"), ("history_rs", "rs_collected_at")):
            collected = getattr(row, attr) if row else None
            expired = not collected or now - collected >= HISTORY_TTL
            job = jobs.get((kind, period))
            if expired and listed:
                await enqueue(session, code, kind, now, start=period, end=period, priority=15)
                # 기존 실패 작업의 재시도 시각을 존중한다.
                waiting = bool(job and job.status == "failed" and job.next_run_at > now)
                pending |= not waiting
                if waiting:
                    retries.append(max(3, int((job.next_run_at - now).total_seconds())))
                else:
                    retries.append(3)
            if job and job.error_code:
                failure = True
    investment.refreshing |= pending
    if failure:
        investment.status = "stale"
    if retries:
        investment.retry_after_seconds = min(
            [
                *retries,
                *(
                    [investment.retry_after_seconds]
                    if investment.retry_after_seconds is not None
                    else []
                ),
            ]
        )
    return investment
