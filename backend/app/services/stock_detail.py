"""종목 상세의 캐시/수집 계약. API 요청에서는 외부 네트워크에 접근하지 않는다."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.stock import (
    Stock,
    StockCollectionJob,
    StockCollectionState,
    StockDailyPrice,
    StockDataCoverage,
    StockMetricSnapshot,
    StockQuoteSnapshot,
)
from app.repositories.stock import enqueue, touch
from app.schemas.stock import (
    Candle,
    Coverage,
    MetricsData,
    QuoteData,
    Resource,
    StockIdentity,
    StockOverview,
    StockPrices,
)

SNAPSHOT_TTL = 60
PRICE_TTL = 86400
ACTIVE_WINDOW = timedelta(minutes=10)
EPOCH = date(1970, 1, 1)


def market_open(now: datetime) -> bool:
    local = now.astimezone(ZoneInfo("Asia/Seoul"))
    return local.weekday() < 5 and (9, 0) <= (local.hour, local.minute) < (15, 40)


def snapshot_ttl(now: datetime) -> int:
    # 휴장일 달력 미도입: 주말/장외에는 1시간 캐시, 장중에는 1분.
    return SNAPSHOT_TTL if market_open(now) else 3600


async def require_stock(session: AsyncSession, code: str) -> Stock:
    stock = await session.get(Stock, code)
    if stock:
        return stock
    if await session.scalar(select(Stock.code).limit(1)) is None:
        raise AppError(
            "CATALOG_PENDING", "종목 목록을 준비 중입니다. 잠시 후 다시 시도해주세요.", 503
        )
    raise AppError("STOCK_NOT_FOUND", "등록되지 않은 종목입니다.", 404)


def resource_state(data, collected_at, state, refreshing, expired, now, source_as_of=None):
    error = state.error_code if state else None
    status = (
        ("stale" if error or expired else "ready")
        if data is not None
        else ("unavailable" if error else "pending")
    )
    retry = (
        max(3, int((state.next_retry_at - now).total_seconds()))
        if state and state.next_retry_at and state.next_retry_at > now
        else 3
    )
    return {
        "status": status,
        "refreshing": refreshing,
        "data": data,
        "source_as_of": source_as_of,
        "collected_at": collected_at,
        "retry_after_seconds": retry if refreshing or error or data is None else None,
    }


async def overview(session: AsyncSession, code: str) -> StockOverview:
    stock = await require_stock(session, code)
    now = datetime.now(UTC)
    quote = await session.get(StockQuoteSnapshot, code)
    metrics = await session.get(StockMetricSnapshot, code)
    state = await session.get(StockCollectionState, (code, "snapshot"))
    quote_state = await session.get(StockCollectionState, (code, "quote")) or state
    metric_state = await session.get(StockCollectionState, (code, "metrics")) or state
    quote_expired = not quote or (now - quote.collected_at).total_seconds() >= snapshot_ttl(now)
    metrics_expired = not metrics or (now - metrics.collected_at).total_seconds() >= snapshot_ttl(
        now
    )
    expired = quote_expired or metrics_expired
    await touch(session, code, "snapshot", now)
    if stock.listing_status == "listed" and expired:
        await enqueue(session, code, "snapshot", now, priority=0)
    job = await session.scalar(
        select(StockCollectionJob).where(
            StockCollectionJob.stock_code == code, StockCollectionJob.resource == "snapshot"
        )
    )
    refreshing = bool(job and job.status in ("queued", "running"))
    response = StockOverview(
        stock=StockIdentity.model_validate(stock),
        quote=Resource[QuoteData](
            **resource_state(
                QuoteData.model_validate(quote) if quote else None,
                quote.collected_at if quote else None,
                quote_state,
                refreshing,
                quote_expired,
                now,
                quote.source_as_of if quote else None,
            )
        ),
        metrics=Resource[MetricsData](
            **resource_state(
                MetricsData.model_validate(metrics) if metrics else None,
                metrics.collected_at if metrics else None,
                metric_state,
                refreshing,
                metrics_expired,
                now,
                metrics.source_as_of if metrics else None,
            )
        ),
    )
    if stock.listing_status == "inactive":
        for resource in (response.quote, response.metrics):
            if resource.data is None:
                resource.status = "unavailable"
            resource.refreshing = False
            resource.retry_after_seconds = None
    await session.commit()
    return response


def requested_range(
    period: str, listed_at: date | None, today: date, from_date: date | None = None
) -> tuple[date, date]:
    end = today - timedelta(days=1)  # 완성된 일봉만; 오늘 시세는 overview에서 조회한다.
    days = {"1M": 31, "3M": 93, "1Y": 366, "5Y": 366 * 5}
    start = (
        (listed_at or date(1990, 1, 1))
        if period == "ALL"
        else end - timedelta(days=days[period] - 1)
    )
    if from_date is not None:
        if from_date > end:
            raise AppError("INVALID_DATE_RANGE", "조회 시작일은 기준일보다 미래일 수 없습니다.", 422)
        start = min(start, from_date)
    start = max(start, listed_at or date(1990, 1, 1))
    return min(start, end), end


def chunks(start: date, end: date):
    # 절대 날짜에 고정된 90일 구간: 1년/5년 탭 전환 시 같은 구간 작업을 재사용한다.
    cursor = EPOCH + timedelta(days=((start - EPOCH).days // 90) * 90)
    while cursor <= end:
        boundary = cursor + timedelta(days=89)
        yield cursor, min(boundary, end)
        cursor = boundary + timedelta(days=1)


async def prices(
    session: AsyncSession, code: str, period: str, from_date: date | None = None
) -> StockPrices:
    stock = await require_stock(session, code)
    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    start, end = requested_range(period, stock.listed_at, today, from_date)
    await touch(session, code, "prices", now)
    covers = list(
        (
            await session.scalars(
                select(StockDataCoverage).where(
                    StockDataCoverage.stock_code == code,
                    StockDataCoverage.adjustment_type == "raw",
                    StockDataCoverage.range_end >= start,
                    StockDataCoverage.range_start <= end,
                )
            )
        ).all()
    )
    complete = True
    relevant_jobs = []
    for left, right in reversed(list(chunks(start, end))):
        cover = next((c for c in covers if c.range_start <= left and c.range_end >= right), None)
        # 과거 구간도 주간 재확인, 최근 구간은 매일 확인하여 원천 정정 반영.
        ttl = PRICE_TTL if right >= today - timedelta(days=14) else PRICE_TTL * 7
        fresh = cover and (now - cover.checked_at).total_seconds() < ttl
        if not fresh:
            complete = False
            if stock.listing_status == "listed":
                await enqueue(
                    session,
                    code,
                    "prices",
                    now,
                    left,
                    right,
                    priority=10 + (end - right).days // 90,
                )
        relevant_jobs.append((left, right))
    jobs = list(
        (
            await session.scalars(
                select(StockCollectionJob).where(
                    StockCollectionJob.stock_code == code,
                    StockCollectionJob.resource == "prices",
                    StockCollectionJob.range_end >= start,
                    StockCollectionJob.range_start <= end,
                )
            )
        ).all()
    )
    jobs = [j for j in jobs if (j.range_start, j.range_end) in relevant_jobs]
    refreshing = any(j.status in ("queued", "running") for j in jobs)
    failed = [j for j in jobs if j.status == "failed"]
    rows = list(
        (
            await session.scalars(
                select(StockDailyPrice)
                .where(
                    StockDailyPrice.stock_code == code,
                    StockDailyPrice.adjustment_type == "raw",
                    StockDailyPrice.trade_date.between(start, end),
                )
                .order_by(StockDailyPrice.trade_date)
            )
        ).all()
    )
    data = [
        Candle(
            date=r.trade_date, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume
        )
        for r in rows
    ]
    status = (
        ("ready" if data else "empty")
        if complete
        else ("stale" if data else "unavailable" if failed else "pending")
    )
    retry = max(3, int((min(j.next_run_at for j in failed) - now).total_seconds())) if failed else 3
    response = StockPrices(
        code=code,
        period=period,
        coverage=Coverage(from_date=start, to_date=end, complete=bool(complete)),
        status=status,
        refreshing=refreshing,
        data=data if data or complete else None,
        collected_at=max((c.checked_at for c in covers), default=None),
        retry_after_seconds=retry if not complete else None,
    )
    if stock.listing_status == "inactive" and not complete:
        response.status = "stale" if data else "unavailable"
        response.refreshing = False
        response.retry_after_seconds = None
    await session.commit()
    return response
