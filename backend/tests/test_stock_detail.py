from datetime import UTC, date, datetime, timedelta

import pytest
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import engine, get_session
from app.main import app
from app.models.stock import Stock, StockCollectionJob, StockQuoteSnapshot
from app.repositories import stock as repo
from app.schemas.stock import StockOverview, StockPrices
from app.services import stock_detail


@pytest.fixture
async def stock_db():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with factory() as session:
            session.add(
                Stock(
                    code="TST001",
                    name="테스트 종목",
                    market="KOSPI",
                    listing_status="listed",
                    listed_at=date(2020, 1, 1),
                    synced_at=datetime.now(UTC),
                )
            )
            await session.commit()

        async def override():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override
        try:
            yield factory
        finally:
            app.dependency_overrides.pop(get_session, None)
            await transaction.rollback()


@respx.mock
async def test_cold_request_enqueues_once_without_external_io(stock_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(2):
            response = await client.get("/api/stocks/TST001/overview")
            assert response.status_code == 200
            body = response.json()
            StockOverview.model_validate(body)
            assert body["quote"]["status"] == "pending"
            assert body["quote"]["refreshing"] is True
            assert body["quote"]["data"] is None
        for _ in range(2):
            response = await client.get("/api/stocks/TST001/prices?period=1Y")
            assert response.status_code == 200
            StockPrices.model_validate(response.json())
            assert response.json()["status"] == "pending"
    async with stock_db() as session:
        jobs = (
            await session.scalars(
                select(StockCollectionJob).where(StockCollectionJob.stock_code == "TST001")
            )
        ).all()
        assert len([j for j in jobs if j.resource == "snapshot"]) == 1
        assert 4 <= len([j for j in jobs if j.resource == "prices"]) <= 6
        assert all((j.range_end - j.range_start).days <= 89 for j in jobs)
    assert len(respx.calls) == 0


async def test_http_unknown_stock_and_invalid_period(stock_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/stocks/ZZZZZZ/overview")).status_code == 404
        assert (await client.get("/api/stocks/bad/overview")).status_code == 422
        assert (await client.get("/api/stocks/TST001/prices?period=10Y")).status_code == 422


async def test_quote_and_metrics_preserve_nulls_and_fail_independently(stock_db):
    from app.collectors.stocks import StockWorker

    now = datetime.now(UTC)
    async with stock_db() as session:
        await repo.touch(session, "TST001", "snapshot", now)
        await repo.save_snapshot(
            session,
            "TST001",
            {
                "price": 100,
                "change": 1,
                "change_amount": 1,
                "volume": 0,
                "trading_value": 0,
                "market_cap": None,
                "source_as_of": None,
            },
            {
                "per": None,
                "pbr": 0,
                "eps": -10,
                "bps": 0,
                "foreign_ownership": None,
                "week52_high": None,
                "week52_low": None,
            },
            now,
        )
        await StockWorker._state(session, "TST001", "quote", None, True, now)
        await StockWorker._state(session, "TST001", "metrics", "INVALID_METRICS", False, now)
        await session.commit()
    async with stock_db() as session:
        result = await stock_detail.overview(session, "TST001")
        assert result.quote.status == "ready"
        assert result.metrics.status == "stale"
        assert result.quote.data.market_cap is None
        assert result.quote.data.volume == 0
        assert result.metrics.data.per is None
        assert result.metrics.data.pbr == 0
        assert result.quote.source_as_of is None


async def test_complete_empty_price_range_does_not_requeue(stock_db):
    now = datetime.now(UTC)
    async with stock_db() as session:
        await stock_detail.prices(session, "TST001", "1M")
        jobs = (
            await session.scalars(
                select(StockCollectionJob).where(
                    StockCollectionJob.stock_code == "TST001",
                    StockCollectionJob.resource == "prices",
                )
            )
        ).all()
        for job in jobs:
            await repo.save_prices(session, job, [], now)
            job.status = "idle"
        await session.commit()
    async with stock_db() as session:
        result = await stock_detail.prices(session, "TST001", "1M")
        assert result.status == "empty"
        assert result.coverage.complete is True
        assert result.data == []
        assert not result.refreshing


@pytest.mark.parametrize("incoming", ["older", "unknown"])
async def test_snapshot_old_source_timestamp_cannot_overwrite(stock_db, incoming):
    now = datetime.now(UTC)
    quote = {
        "price": 100,
        "change": 0,
        "change_amount": 0,
        "volume": 1,
        "trading_value": 100,
        "market_cap": 1000,
        "source_as_of": now,
    }
    async with stock_db() as session:
        await repo.save_snapshot(session, "TST001", quote, {}, now)
        await repo.save_snapshot(
            session,
            "TST001",
            {
                **quote,
                "price": 50,
                "source_as_of": now - timedelta(days=1) if incoming == "older" else None,
            },
            None,
            now,
        )
        saved = await session.get(StockQuoteSnapshot, "TST001")
        assert saved.price == 100


def test_chart_chunks_do_not_exceed_api_limit_and_overlap_is_reused():
    short = set(stock_detail.chunks(date(2026, 8, 1), date(2026, 9, 18)))
    long = set(stock_detail.chunks(date(2025, 9, 18), date(2026, 9, 18)))
    assert short <= long
    assert all((end - start).days < 90 for start, end in long)


async def test_missing_metrics_does_not_make_fresh_quote_stale(stock_db):
    now = datetime.now(UTC)
    async with stock_db() as session:
        await repo.save_snapshot(
            session,
            "TST001",
            {
                "price": 100,
                "change": 0,
                "change_amount": 0,
                "volume": 0,
                "trading_value": 0,
                "market_cap": None,
            },
            None,
            now,
        )
        await session.commit()
    async with stock_db() as session:
        response = await stock_detail.overview(session, "TST001")
        assert response.quote.status == "ready"
        assert response.metrics.status == "pending"
        assert response.metrics.refreshing


async def test_inactive_stock_has_terminal_state_without_queueing(stock_db):
    async with stock_db() as session:
        stock = await session.get(Stock, "TST001")
        stock.listing_status = "inactive"
        await session.commit()
    async with stock_db() as session:
        response = await stock_detail.overview(session, "TST001")
        assert response.quote.status == "unavailable"
        assert response.quote.retry_after_seconds is None
        response = await stock_detail.prices(session, "TST001", "1Y")
        assert response.status == "unavailable"
        assert not response.refreshing
        assert response.retry_after_seconds is None
        assert not (
            await session.scalars(
                select(StockCollectionJob).where(StockCollectionJob.stock_code == "TST001")
            )
        ).all()
