import re
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import engine, get_session
from app.core.mvp_stocks import MVP_CODES, MVP_STOCKS, MvpStock
from app.main import app
from app.models.stock import Stock, StockCollectionJob, StockCollectionState
from app.repositories import stock as repo
from app.schemas.stock import StockList
from app.services import stock_list
from app.services.krx import SECTOR_NAMES


def stock(code, name, market="KOSPI", status="listed"):
    return Stock(
        code=code,
        name=name,
        market=market,
        listing_status=status,
        listed_at=date(2020, 1, 1),
        synced_at=datetime.now(UTC),
    )


@pytest.fixture
async def list_db(monkeypatch):
    # 고정 목록은 테스트용 종목으로 바꾼다. 순위 순서가 코드 순서와 다르게 둔다.
    mvp = (
        MvpStock(1, "TST002", "순위1", "전기전자"),
        MvpStock(2, "TST001", "순위2", "금융"),
        MvpStock(3, "TST004", "순위3-비활성", "화학"),
        MvpStock(4, "TST005", "순위4-DB없음", "건설"),
    )
    monkeypatch.setattr(stock_list, "MVP_STOCKS", mvp)
    monkeypatch.setattr(stock_list, "MVP_CODES", frozenset(m.code for m in mvp))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with factory() as session:
            session.add_all(
                [
                    stock("TST001", "DB이름2", "KOSDAQ"),
                    stock("TST002", "DB이름1"),
                    stock("TST003", "목록밖"),
                    stock("TST004", "비활성", status="inactive"),
                ]
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


async def test_list_is_ordered_by_rank_and_camel_case(list_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/stocks")
    assert response.status_code == 200
    body = response.json()
    StockList.model_validate(body)
    assert set(body) == {"items"}
    assert body["items"] == [
        {"rank": 1, "code": "TST002", "name": "DB이름1", "market": "KOSPI", "sector": "전기전자"},
        {"rank": 2, "code": "TST001", "name": "DB이름2", "market": "KOSDAQ", "sector": "금융"},
    ]


async def test_list_excludes_inactive_unknown_and_non_mvp(list_db):
    async with list_db() as session:
        result = await stock_list.stock_list(session)
    codes = [item.code for item in result.items]
    assert "TST003" not in codes  # 목록 밖
    assert "TST004" not in codes  # inactive
    assert "TST005" not in codes  # stock 테이블에 없음
    assert codes == ["TST002", "TST001"]


async def test_list_does_not_enqueue_collection(list_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/stocks")
    async with list_db() as session:
        for model in (StockCollectionJob, StockCollectionState):
            rows = await session.scalars(
                select(model.stock_code).where(model.stock_code.like("TST%"))
            )
            assert rows.all() == []


async def test_list_returns_503_when_catalog_is_not_ready(monkeypatch):
    async def empty(session, codes):
        return []

    async def never_synced(session):
        return None

    async def override():
        yield None

    monkeypatch.setattr(repo, "listed_by_codes", empty)
    monkeypatch.setattr(repo, "catalog_checked_at", never_synced)
    app.dependency_overrides[get_session] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/stocks")
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "CATALOG_PENDING",
            "message": "종목 목록을 준비 중입니다. 잠시 후 다시 시도해주세요.",
        }
    }


def test_mvp_stocks_definition_is_consistent():
    assert len(MVP_STOCKS) == 100
    assert [m.rank for m in MVP_STOCKS] == list(range(1, 101))
    assert len({m.code for m in MVP_STOCKS}) == 100
    assert len({m.name for m in MVP_STOCKS}) == 100
    assert MVP_CODES == {m.code for m in MVP_STOCKS}
    assert all(re.fullmatch(r"[0-9A-Z]{6}", m.code) for m in MVP_STOCKS)


def test_mvp_stock_sectors_match_krx_sector_names():
    # 홈 업종 순위가 쓰는 KRX 업종지수 이름과 같아야 프론트가 이름으로 연결할 수 있다.
    assert all(m.sector for m in MVP_STOCKS)
    assert {m.sector for m in MVP_STOCKS} <= SECTOR_NAMES
