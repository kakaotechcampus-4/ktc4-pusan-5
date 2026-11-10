import calendar
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.models.stock import Stock, StockCollectionJob, StockDailyPrice
from app.repositories.stock import enqueue
from app.repositories.stock_history import HISTORY_TTL, history_for


def per(market_cap: float | None, net_income_ttm: float | None) -> float | None:
    """분기말 시가총액 ÷ 최근 4분기 순이익. 적자·0이면 의미가 없어 None."""
    if market_cap is None or net_income_ttm is None or net_income_ttm <= 0:
        return None
    return market_cap / net_income_ttm


def pbr(close: float | None, bps: float | None) -> float | None:
    """분기말 종가 ÷ BPS. BPS가 0 이하(자본잠식)면 None."""
    if close is None or bps is None or bps <= 0:
        return None
    return close / bps


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
    cap_dates = {row.cap_as_of for row in saved.values() if row.cap_as_of is not None}
    closes = {}
    if cap_dates:
        closes = {
            price.trade_date: price.close
            for price in (
                await session.scalars(
                    select(StockDailyPrice).where(
                        StockDailyPrice.stock_code == code,
                        StockDailyPrice.adjustment_type == "raw",
                        StockDailyPrice.trade_date.in_(cap_dates),
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
            point.per = per(point.market_cap, point.net_income_ttm)
            close = closes.get(row.cap_as_of)
            point.pbr = pbr(float(close) if close is not None else None, point.bps)
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
