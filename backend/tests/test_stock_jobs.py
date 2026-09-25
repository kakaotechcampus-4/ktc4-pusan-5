from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import engine
from app.models.stock import Stock, StockCollectionJob
from app.repositories.stock import LEASE_SECONDS, claim, enqueue, owned_job


def _code() -> str:
    return uuid4().hex[:6].upper()


async def _session_with_stock(code: str):
    connection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(
        connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = factory()
    await session.execute(
        Stock.__table__.insert().values(
            code=code,
            name="Test stock",
            market="KOSPI",
            listing_status="listed",
            synced_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return connection, transaction, session


async def _cleanup(code: str) -> None:
    async with engine.begin() as connection:
        await connection.execute(delete(StockCollectionJob).where(StockCollectionJob.stock_code == code))
        await connection.execute(delete(Stock).where(Stock.code == code))


@pytest.mark.asyncio
async def test_enqueue_deduplicates_and_requeues_terminal_job():
    code = _code()
    connection, transaction, session = await _session_with_stock(code)
    now = datetime.now(UTC)
    try:
        await enqueue(session, code, "prices", now, date(2026, 1, 1), date(2026, 1, 31))
        await session.flush()
        await enqueue(session, code, "prices", now + timedelta(seconds=1), date(2026, 1, 1), date(2026, 1, 31))
        await session.flush()
        rows = (
            await session.scalars(
                select(StockCollectionJob).where(StockCollectionJob.stock_code == code)
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "queued"

        rows[0].status = "failed"
        rows[0].next_run_at = now
        await session.flush()
        await enqueue(session, code, "prices", now + timedelta(seconds=2), date(2026, 1, 1), date(2026, 1, 31), priority=2)
        await session.flush()
        await session.refresh(rows[0])
        assert rows[0].status == "queued"
        assert rows[0].priority == 2
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await _cleanup(code)


@pytest.mark.asyncio
async def test_enqueue_resets_attempts_and_reopens_budget_at_hard_limit():
    code = _code()
    connection, transaction, session = await _session_with_stock(code)
    now = datetime.now(UTC)
    try:
        await session.execute(
            StockCollectionJob.__table__.insert().values(
                stock_code=code,
                resource="snapshot",
                range_start=date(1970, 1, 1),
                range_end=date(1970, 1, 1),
                status="failed",
                priority=-1000,
                attempts=5,
                next_run_at=now,
            )
        )
        await session.flush()

        # attempts 가 5 에 도달한 failed job 은 claim() 대상에서 빠지도록 함
        picked = await claim(session, now)
        assert picked is None or picked.stock_code != code

        # 재요청(enqueue)은 실패 이력과 무관하게 attempts를 0으로 reset(재시도 기회 부여)
        await enqueue(session, code, "snapshot", now + timedelta(seconds=1), priority=-1000)
        await session.flush()

        job = await session.scalar(
            select(StockCollectionJob).where(StockCollectionJob.stock_code == code)
        )
        assert job.status == "queued"
        assert job.attempts == 0

        claimed = await claim(session, now + timedelta(seconds=1))
        assert claimed is not None
        assert claimed.stock_code == code
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await _cleanup(code)


@pytest.mark.asyncio
async def test_claim_skips_job_locked_by_another_worker():
    code = _code()
    now = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                Stock.__table__.insert().values(
                    code=code,
                    name="Test stock",
                    market="KOSPI",
                    listing_status="listed",
                    synced_at=now,
                )
            )
            await connection.execute(
                StockCollectionJob.__table__.insert().values(
                    stock_code=code,
                    resource="snapshot",
                    range_start=date(1970, 1, 1),
                    range_end=date(1970, 1, 1),
                    status="queued",
                    priority=-1000,
                    attempts=0,
                    next_run_at=now,
                )
            )

        first_connection = await engine.connect()
        second_connection = await engine.connect()
        first_transaction = await first_connection.begin()
        second_transaction = await second_connection.begin()
        try:
            first_factory = async_sessionmaker(first_connection, expire_on_commit=False)
            second_factory = async_sessionmaker(second_connection, expire_on_commit=False)
            async with first_factory() as first, second_factory() as second:
                first_job = await claim(first, now)
                assert first_job is not None
                second_job = await claim(second, now)
                assert first_job.stock_code == code
                # 개발 DB의 다른 대기 작업은 정상적으로 가져올 수 있다.
                assert second_job is None or second_job.id != first_job.id
        finally:
            await first_transaction.rollback()
            await second_transaction.rollback()
            await first_connection.close()
            await second_connection.close()
    finally:
        await _cleanup(code)


@pytest.mark.asyncio
async def test_expired_lease_cannot_fence_new_owner():
    code = _code()
    connection, transaction, session = await _session_with_stock(code)
    now = datetime.now(UTC)
    try:
        await enqueue(session, code, "snapshot", now)
        await session.flush()
        first = await claim(session, now)
        assert first is not None
        old_token = first.lease_token
        await session.flush()

        second = await claim(session, now + timedelta(seconds=LEASE_SECONDS + 1))
        assert second is not None
        assert second.lease_token != old_token
        assert await owned_job(session, first.id, old_token, now + timedelta(seconds=LEASE_SECONDS + 1)) is None
        assert await owned_job(session, second.id, second.lease_token, now + timedelta(seconds=1)) is not None
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await _cleanup(code)
