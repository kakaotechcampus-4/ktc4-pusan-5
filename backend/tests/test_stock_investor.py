from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.models.stock import StockCollectionJob, StockCollectionState
from app.repositories import stock as repo
from app.services import stock_detail
from app.services.market_calendar import KST
from app.services.stock_data import InvestorFlow
from tests.test_stock_snapshot_schedule import _worker

pytest_plugins = ("tests.test_stock_detail",)


def _flow(day, qty=-1250, value=Decimal(-85_000_000)):
    return InvestorFlow(day, qty, value)


async def _job(session, code):
    return await session.scalar(
        select(StockCollectionJob).where(
            StockCollectionJob.stock_code == code, StockCollectionJob.resource == "investor"
        )
    )


async def test_overview_investor_flow_is_pending_until_collected(stock_db):
    async with stock_db() as session:
        result = await stock_detail.overview(session, "TST001")
    flow = result.investor_flow
    assert flow.status == "pending" and flow.data is None
    # 수집기가 정기 수집하므로 조회가 작업을 등록하지 않는다.
    assert flow.refreshing is False and flow.retry_after_seconds == 3


async def test_overview_returns_saved_investor_flow_with_raw_numbers(stock_db):
    now = datetime.now(UTC)
    source_as_of = datetime(2026, 10, 30, 15, 30, tzinfo=KST)
    async with stock_db() as session:
        assert await repo.save_investor(session, "TST001", _flow(date(2026, 10, 30)), source_as_of, now)
        await session.commit()
    async with stock_db() as session:
        result = await stock_detail.overview(session, "TST001")
    flow = result.investor_flow
    assert flow.status == "ready"
    assert flow.data.trade_date == date(2026, 10, 30)
    assert flow.data.institution_net_qty == -1250
    assert flow.data.institution_net_value == -85_000_000
    assert flow.source_as_of == source_as_of and flow.collected_at == now
    dumped = result.model_dump(mode="json", by_alias=True)["investorFlow"]["data"]
    assert dumped == {
        "tradeDate": "2026-10-30",
        "institutionNetQty": -1250,
        "institutionNetValue": -85_000_000,
    }


async def test_older_trade_date_never_overwrites_newer_one(stock_db):
    now = datetime.now(UTC)
    as_of = datetime(2026, 10, 30, 15, 30, tzinfo=KST)
    async with stock_db() as session:
        assert await repo.save_investor(session, "TST001", _flow(date(2026, 10, 30), 10), as_of, now)
        assert not await repo.save_investor(session, "TST001", _flow(date(2026, 10, 29), 99), as_of, now)
        # 같은 거래일의 재수집은 갱신된다(장중 잠정치 -> 확정치).
        assert await repo.save_investor(session, "TST001", _flow(date(2026, 10, 30), 11), as_of, now)
        await session.commit()
    async with stock_db() as session:
        result = await stock_detail.overview(session, "TST001")
    assert result.investor_flow.data.institution_net_qty == 11


async def test_investors_are_queued_by_the_collector_and_not_requeued_while_fresh(
    stock_db, monkeypatch
):
    worker = _worker(monkeypatch, stock_db)
    await worker.schedule_investors()
    async with stock_db() as session:
        job = await _job(session, "TST001")
        assert job is not None and job.status == "queued" and job.priority == 3
        # finish() 가 성공 시각을 남길 수 있도록 상태 행이 먼저 만들어져 있어야 한다.
        assert await session.get(StockCollectionState, ("TST001", "investor")) is not None
        job.status = "running"
        job.attempts = 1
        await repo.finish(session, job, None, datetime.now(UTC))
        await session.commit()

    worker.investor_checked_at = datetime.min.replace(tzinfo=UTC)
    await worker.schedule_investors()
    async with stock_db() as session:
        assert (await _job(session, "TST001")).status == "idle"
