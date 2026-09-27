"""영속 작업의 중복 방지·임대·결과 저장. 외부 호출은 하지 않는다."""

from datetime import date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock import (
    Stock,
    StockCollectionJob,
    StockCollectionState,
    StockDailyPrice,
    StockDataCoverage,
    StockMetricSnapshot,
    StockQuoteSnapshot,
)

SENTINEL = date(1970, 1, 1)
LEASE_SECONDS = 60


async def touch(session: AsyncSession, code: str, resource: str, now: datetime) -> None:
    statement = insert(StockCollectionState).values(
        stock_code=code, resource=resource, last_requested_at=now
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["stock_code", "resource"],
            set_={"last_requested_at": now},
            where=StockCollectionState.last_requested_at < now - timedelta(seconds=30),
        )
    )


async def enqueue(
    session: AsyncSession,
    code: str,
    resource: str,
    now: datetime,
    start: date = SENTINEL,
    end: date = SENTINEL,
    priority: int = 10,
) -> None:
    statement = insert(StockCollectionJob).values(
        stock_code=code,
        resource=resource,
        range_start=start,
        range_end=end,
        status="queued",
        priority=priority,
        attempts=0,
        next_run_at=now,
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_stock_job_range",
            # 재요청은 실패 구간과 무관하게 재시도 기회 부여함
            set_={"status": "queued", "next_run_at": now, "priority": priority, "attempts": 0},
            where=and_(
                StockCollectionJob.status.in_(["idle", "failed"]),
                StockCollectionJob.next_run_at <= now,
            ),
        )
    )


async def claim(session: AsyncSession, now: datetime) -> StockCollectionJob | None:
    job = await session.scalar(
        select(StockCollectionJob)
        .join(Stock, Stock.code == StockCollectionJob.stock_code)
        .where(
            Stock.listing_status == "listed",
            or_(
                and_(
                    or_(
                        StockCollectionJob.status == "queued",
                        and_(
                            StockCollectionJob.status == "failed", StockCollectionJob.attempts < 5
                        ),
                    ),
                    StockCollectionJob.next_run_at <= now,
                ),
                and_(StockCollectionJob.status == "running", StockCollectionJob.lease_until <= now),
            ),
        )
        .order_by(
            StockCollectionJob.priority, StockCollectionJob.next_run_at, StockCollectionJob.id
        )
        .with_for_update(skip_locked=True, of=StockCollectionJob)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "running"
    job.lease_token = str(uuid4())
    job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    job.attempts += 1
    return job


async def owned_job(session: AsyncSession, job_id: int, token: str, now: datetime):
    # 만료된 워커는 새 워커의 결과를 덮어쓰거나 작업을 완료 처리할 수 없다.
    return await session.scalar(
        select(StockCollectionJob)
        .where(
            StockCollectionJob.id == job_id,
            StockCollectionJob.status == "running",
            StockCollectionJob.lease_token == token,
            StockCollectionJob.lease_until > now,
        )
        .with_for_update()
    )


async def finish(session: AsyncSession, job: StockCollectionJob, error: str | None, now: datetime):
    delay = min(900, 30 * 2 ** min(job.attempts - 1, 5)) if error else 0
    job.status = "failed" if error else "idle"
    job.error_code = error
    job.next_run_at = now + timedelta(seconds=delay)
    job.lease_until = None
    job.lease_token = None
    if not error:
        job.attempts = 0
    values = {
        "last_attempt_at": now,
        "next_retry_at": job.next_run_at if error else None,
        "error_code": error,
    }
    if not error:
        values["last_success_at"] = now
    await session.execute(
        update(StockCollectionState)
        .where(
            StockCollectionState.stock_code == job.stock_code,
            StockCollectionState.resource == job.resource,
        )
        .values(**values)
    )


async def save_snapshot(
    session: AsyncSession, code: str, quote: dict | None, metrics: dict | None, now: datetime
):
    rejected = set()
    for model, data in ((StockQuoteSnapshot, quote), (StockMetricSnapshot, metrics)):
        if data is None:
            continue
        values = {**data, "stock_code": code, "collected_at": now, "source": "KIS"}
        statement = insert(model).values(**values)
        # 원천 시각이 있을 때에는 오래된 응답으로 역전시키지 않는다.
        newer = or_(
            model.source_as_of.is_(None),
            model.source_as_of <= statement.excluded.source_as_of,
        )
        result = await session.execute(
            statement.on_conflict_do_update(
                index_elements=["stock_code"],
                set_={k: statement.excluded[k] for k in values if k != "stock_code"},
                where=newer,
            )
        )
        if result.rowcount == 0:
            rejected.add("quote" if model is StockQuoteSnapshot else "metrics")
    return rejected


async def save_prices(
    session: AsyncSession, job: StockCollectionJob, rows: list[dict], now: datetime
):
    if rows:
        statement = insert(StockDailyPrice).values(
            [
                {
                    **row,
                    "stock_code": job.stock_code,
                    "adjustment_type": "raw",
                    "source": "KIS",
                    "collected_at": now,
                }
                for row in rows
            ]
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["stock_code", "trade_date", "adjustment_type"],
                set_={
                    key: statement.excluded[key]
                    for key in ("open", "high", "low", "close", "volume", "collected_at", "source")
                },
            )
        )
    statement = insert(StockDataCoverage).values(
        stock_code=job.stock_code,
        adjustment_type="raw",
        range_start=job.range_start,
        range_end=job.range_end,
        checked_at=now,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["stock_code", "adjustment_type", "range_start", "range_end"],
            set_={"checked_at": now},
        )
    )


async def sync_catalog(session: AsyncSession, rows: list[dict], now: datetime):
    # Provider validates complete two-market snapshot before this transaction.
    if not rows or len({r["code"] for r in rows}) != len(rows):
        raise ValueError("INVALID_CATALOG")
    for offset in range(0, len(rows), 500):
        statement = insert(Stock).values(
            [
                {**r, "listing_status": "listed", "synced_at": now}
                for r in rows[offset : offset + 500]
            ]
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["code"],
                set_={
                    k: statement.excluded[k]
                    for k in ("name", "market", "listing_status", "listed_at", "synced_at")
                },
            )
        )
    await session.execute(
        update(Stock).where(Stock.synced_at < now).values(listing_status="inactive")
    )


async def catalog_checked_at(session: AsyncSession):
    return await session.scalar(select(func.max(Stock.synced_at)))
