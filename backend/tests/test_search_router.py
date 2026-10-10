from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.models import Concept, Stock
from app.routers import search as search_router

# 실제 종목과 겹치지 않도록 쓰지 않는 단어를 쓴다.
_STOCKS = [
    ("9S0001", "대쿼카", "KOSPI", "listed"),
    ("9S0002", "쿼카전자", "KOSDAQ", "listed"),
    ("9S0003", "쿼카", "KOSPI", "listed"),
    ("9S0004", "쿼카폐지", "KOSPI", "inactive"),
    ("9S0005", "100%쿼카", "KOSPI", "listed"),
]
# 고정 목록(MVP) 밖 종목. 이름이 일치해도 검색되면 안 된다.
_OUTSIDE_CODE = "9S0006"
_OUTSIDE_STOCK = (_OUTSIDE_CODE, "쿼카밖", "KOSPI", "listed")
_CONCEPT_SLUG = "search-test-quokka"


@pytest.fixture(autouse=True)
def mvp_codes(monkeypatch):
    # 검색은 고정 목록 안에서만 한다. 테스트 종목 중 _OUTSIDE_CODE 만 목록에서 뺀다.
    monkeypatch.setattr(
        search_router, "MVP_CODES", frozenset(code for code, *_ in _STOCKS)
    )


async def _cleanup() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Stock).where(Stock.code.like("9S%")))
        await session.execute(delete(Concept).where(Concept.slug == _CONCEPT_SLUG))
        await session.commit()


async def _seed() -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        session.add_all(
            Stock(code=code, name=name, market=market, listing_status=status, synced_at=now)
            for code, name, market, status in [*_STOCKS, _OUTSIDE_STOCK]
        )
        session.add(
            Concept(
                slug=_CONCEPT_SLUG,
                name="쿼카효과",
                aliases=["웃는동물효과"],
                category="shareholder-return/dividend",
                summary="검색 테스트용 개념",
                body="본문",
                sources=[],
            )
        )
        await session.commit()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_search_orders_exact_then_prefix_then_contains_and_skips_inactive():
    await _cleanup()
    await _seed()
    try:
        async with _client() as client:
            resp = await client.get("/api/search", params={"q": "쿼카"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "쿼카"
        # 정확 일치 → 이름 앞부분 일치 → 이름에 포함(짧은 이름 먼저). 상장폐지(inactive)는 제외.
        assert [s["code"] for s in body["stocks"]] == ["9S0003", "9S0002", "9S0001", "9S0005"]
        assert body["stocks"][0] == {"code": "9S0003", "name": "쿼카", "market": "KOSPI"}
    finally:
        await _cleanup()


async def test_search_only_returns_stocks_in_fixed_list():
    await _cleanup()
    await _seed()
    try:
        async with _client() as client:
            by_name = await client.get("/api/search", params={"q": "쿼카밖"})
            by_code = await client.get("/api/search", params={"q": _OUTSIDE_CODE})
        assert by_name.json()["stocks"] == []
        assert by_code.json()["stocks"] == []
    finally:
        await _cleanup()


async def test_search_matches_code_prefix():
    await _cleanup()
    await _seed()
    try:
        async with _client() as client:
            resp = await client.get("/api/search", params={"q": "9s000"})
        assert {s["code"] for s in resp.json()["stocks"]} == {"9S0001", "9S0002", "9S0003", "9S0005"}
    finally:
        await _cleanup()


async def test_search_treats_wildcards_as_plain_text():
    await _cleanup()
    await _seed()
    try:
        async with _client() as client:
            percent = await client.get("/api/search", params={"q": "%"})
            underscore = await client.get("/api/search", params={"q": "_"})
        assert [s["code"] for s in percent.json()["stocks"]] == ["9S0005"]
        assert underscore.json()["stocks"] == []
    finally:
        await _cleanup()


async def test_search_finds_concepts_by_name_and_alias():
    await _cleanup()
    await _seed()
    try:
        async with _client() as client:
            by_name = await client.get("/api/search", params={"q": "쿼카효과"})
            by_alias = await client.get("/api/search", params={"q": "웃는동물"})
        for resp in (by_name, by_alias):
            assert resp.json()["concepts"] == [
                {"slug": _CONCEPT_SLUG, "name": "쿼카효과", "summary": "검색 테스트용 개념"}
            ]
    finally:
        await _cleanup()


async def test_search_respects_limit_per_kind():
    await _cleanup()
    await _seed()
    try:
        async with _client() as client:
            resp = await client.get("/api/search", params={"q": "쿼카", "limit": 1})
        assert len(resp.json()["stocks"]) == 1
    finally:
        await _cleanup()


async def test_search_rejects_empty_or_too_long_query():
    async with _client() as client:
        empty = await client.get("/api/search", params={"q": ""})
        missing = await client.get("/api/search")
        too_long = await client.get("/api/search", params={"q": "가" * 51})
        blank = await client.get("/api/search", params={"q": "   "})
    for resp in (empty, missing, too_long):
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert blank.status_code == 200
    assert blank.json() == {"query": "", "stocks": [], "concepts": []}
