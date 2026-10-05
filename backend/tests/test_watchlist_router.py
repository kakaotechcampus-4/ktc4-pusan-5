from datetime import UTC, datetime

import httpx
from httpx import ASGITransport
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.core.security import ACCESS_TOKEN_COOKIE, create_access_token
from app.main import app
from app.models import Stock, StockQuoteSnapshot, User

_KAKAO_ID = "test-watchlist-kakao-id"
_CODE = "9T0001"
_CODE_NO_QUOTE = "9T0002"


async def _cleanup() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.kakao_id == _KAKAO_ID))
        codes = [_CODE, _CODE_NO_QUOTE]
        await session.execute(
            delete(StockQuoteSnapshot).where(StockQuoteSnapshot.stock_code.in_(codes))
        )
        await session.execute(delete(Stock).where(Stock.code.in_(codes)))
        await session.commit()


async def _seed() -> int:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        user = User(kakao_id=_KAKAO_ID, nickname="관심", email="watch@example.com")
        session.add(user)
        session.add_all(
            Stock(code=c, name=n, market="KOSPI", synced_at=now)
            for c, n in [(_CODE, "테스트전자"), (_CODE_NO_QUOTE, "무시세")]
        )
        await session.flush()
        session.add(
            StockQuoteSnapshot(
                stock_code=_CODE,
                price=62400,
                change=-1.08,
                change_amount=-680,
                volume=1,
                trading_value=1,
                collected_at=now,
            )
        )
        await session.commit()
        return user.id


def _client(user_id: int | None = None) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    if user_id is not None:
        client.cookies.set(ACCESS_TOKEN_COOKIE, create_access_token(user_id))
    return client


async def test_watchlist_requires_login():
    async with _client() as client:
        resp = await client.get("/api/watchlist")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


async def test_watchlist_add_list_remove():
    await _cleanup()
    user_id = await _seed()
    try:
        async with _client(user_id) as client:
            assert (await client.get("/api/watchlist")).json() == {"items": []}

            assert (await client.post("/api/watchlist", json={"stockCode": _CODE})).status_code == 204
            # 중복 추가는 멱등
            assert (await client.post("/api/watchlist", json={"stockCode": _CODE})).status_code == 204
            assert (
                await client.post("/api/watchlist", json={"stockCode": _CODE_NO_QUOTE})
            ).status_code == 204

            items = (await client.get("/api/watchlist")).json()["items"]
            assert [i["code"] for i in items] == [_CODE_NO_QUOTE, _CODE]  # 최근 추가순
            assert items[1]["quote"] == {"price": 62400, "change": -1.08, "changeAmount": -680}
            assert items[1]["asOf"] is not None
            assert items[0]["quote"] is None and items[0]["asOf"] is None

            assert (await client.delete(f"/api/watchlist/{_CODE}")).status_code == 204
            assert (await client.delete(f"/api/watchlist/{_CODE}")).status_code == 204
            items = (await client.get("/api/watchlist")).json()["items"]
            assert [i["code"] for i in items] == [_CODE_NO_QUOTE]
    finally:
        await _cleanup()


async def test_watchlist_add_unknown_stock_returns_404():
    await _cleanup()
    user_id = await _seed()
    try:
        async with _client(user_id) as client:
            resp = await client.post("/api/watchlist", json={"stockCode": "ZZZZZZ"})
        assert resp.status_code == 404
        assert resp.json() == {
            "error": {"code": "STOCK_NOT_FOUND", "message": "종목을 찾을 수 없습니다"}
        }
    finally:
        await _cleanup()
