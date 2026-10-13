from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import engine, get_session
from app.main import app
from app.models.stock import Stock, StockCollectionJob, StockCollectionState

# DB에는 있지만 MVP 고정 목록에는 없는 종목
OUTSIDE = "TST009"
ENDPOINTS = ("overview", "prices", "financials")
NOT_FOUND = {"error": {"code": "STOCK_NOT_FOUND", "message": "등록되지 않은 종목입니다."}}


@pytest.fixture
async def gate_db():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with factory() as session:
            session.add(
                Stock(
                    code=OUTSIDE,
                    name="목록밖",
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


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_stock_outside_mvp_list_is_not_found(gate_db, endpoint):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/stocks/{OUTSIDE}/{endpoint}")
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


async def test_stock_outside_mvp_list_creates_no_collection_work(gate_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for endpoint in ENDPOINTS:
            await client.get(f"/api/stocks/{OUTSIDE}/{endpoint}")
    async with gate_db() as session:
        for model in (StockCollectionJob, StockCollectionState):
            rows = await session.scalars(
                select(model.stock_code).where(model.stock_code == OUTSIDE)
            )
            assert rows.all() == []


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_stock_in_mvp_list_is_still_served(gate_db, monkeypatch, endpoint):
    from app.services import stock_detail

    async with gate_db() as session:
        session.add(
            Stock(
                code="TST010",
                name="목록안",
                market="KOSPI",
                listing_status="listed",
                listed_at=date(2020, 1, 1),
                synced_at=datetime.now(UTC),
            )
        )
        await session.commit()
    monkeypatch.setattr(stock_detail, "MVP_CODES", frozenset({"TST010"}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/stocks/TST010/{endpoint}")
    assert response.status_code == 200
