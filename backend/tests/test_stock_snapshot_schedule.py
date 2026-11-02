from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.collectors import stocks
from app.models.stock import Stock, StockCollectionJob, StockCollectionState
from app.repositories import stock as repo
from app.repositories.market_calendar import upsert_days
from app.services.market_calendar import KST

pytest_plugins = ("tests.test_stock_detail",)


def _worker(monkeypatch, stock_db):
    monkeypatch.setattr(stocks, "SessionLocal", stock_db)
    monkeypatch.setattr(stocks, "MVP_CODES", frozenset({"TST001"}))
    return stocks.StockWorker(None, None)


async def _rescan(worker):
    # 15초 간격 확인을 건너뛰고 바로 다시 훑는다.
    worker.snapshot_checked_at = datetime.min.replace(tzinfo=UTC)
    await worker.schedule_snapshots()


async def _snapshot_job(session, code):
    return await session.scalar(
        select(StockCollectionJob).where(
            StockCollectionJob.stock_code == code, StockCollectionJob.resource == "snapshot"
        )
    )


async def _finish_successfully(session, code):
    # repo.claim 은 대기열 전체에서 꺼내므로 공유 DB 에 남은 다른 작업을 집을 수 있다.
    # 이 종목 작업만 꺼낸 것처럼 바꿔서 완료 처리한다.
    job = await _snapshot_job(session, code)
    job.status = "running"
    job.attempts = 1
    await repo.finish(session, job, None, datetime.now(UTC))
    await session.commit()


async def test_fixed_list_is_queued_without_user_request_and_success_is_recorded(
    stock_db, monkeypatch
):
    worker = _worker(monkeypatch, stock_db)
    await worker.schedule_snapshots()

    async with stock_db() as session:
        job = await _snapshot_job(session, "TST001")
        assert job is not None and job.status == "queued" and job.priority == 0
        # finish() 가 성공 시각을 남길 수 있도록 상태 행이 먼저 만들어져 있어야 한다.
        assert await session.get(StockCollectionState, ("TST001", "snapshot")) is not None
        await _finish_successfully(session, "TST001")

    async with stock_db() as session:
        state = await session.get(StockCollectionState, ("TST001", "snapshot"))
        assert state.last_success_at is not None


async def test_fresh_snapshot_is_not_requeued_until_stale(stock_db, monkeypatch):
    worker = _worker(monkeypatch, stock_db)
    await worker.schedule_snapshots()
    async with stock_db() as session:
        await _finish_successfully(session, "TST001")

    await _rescan(worker)
    async with stock_db() as session:
        assert (await _snapshot_job(session, "TST001")).status == "idle"

    monkeypatch.setattr(stocks, "is_quote_stale", lambda collected_at, now, calendar: True)
    await _rescan(worker)
    async with stock_db() as session:
        assert (await _snapshot_job(session, "TST001")).status == "queued"


async def test_stocks_outside_fixed_list_or_inactive_are_not_queued(stock_db, monkeypatch):
    worker = _worker(monkeypatch, stock_db)
    async with stock_db() as session:
        session.add(
            Stock(
                code="TST002",
                name="목록 밖 종목",
                market="KOSPI",
                listing_status="listed",
                listed_at=date(2020, 1, 1),
                synced_at=datetime.now(UTC),
            )
        )
        stock = await session.get(Stock, "TST001")
        stock.listing_status = "inactive"
        await session.commit()

    await worker.schedule_snapshots()
    async with stock_db() as session:
        assert await _snapshot_job(session, "TST001") is None
        assert await _snapshot_job(session, "TST002") is None


async def test_holiday_daytime_does_not_queue_snapshot(stock_db, monkeypatch):
    # 2026-12-25(금) 휴장일 11:00. 목요일 마감 이후에 받은 값은 다시 받지 않는다.
    now = datetime(2026, 12, 25, 11, 0, tzinfo=KST)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(stocks, "datetime", FixedDatetime)
    worker = _worker(monkeypatch, stock_db)
    async with stock_db() as session:
        await repo.touch(session, "TST001", "snapshot", now)
        state = await session.get(StockCollectionState, ("TST001", "snapshot"))
        state.last_success_at = datetime(2026, 12, 24, 15, 50, tzinfo=KST)
        await upsert_days(session, [(now.date(), False)], now - timedelta(hours=2))
        await session.commit()

    await worker.schedule_snapshots()
    async with stock_db() as session:
        assert await _snapshot_job(session, "TST001") is None
        # 같은 날이 개장일이면 장중이므로 60초가 지난 값은 다시 받는다.
        await upsert_days(session, [(now.date(), True)], now - timedelta(hours=2))
        await session.commit()

    await _rescan(worker)
    async with stock_db() as session:
        assert (await _snapshot_job(session, "TST001")).status == "queued"
