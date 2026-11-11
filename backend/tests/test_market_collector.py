from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.collectors import market
from app.core.database import engine
from app.models.market import MarketSnapshot
from app.services.market_data import MarketDataError, Quote


async def test_one_source_failure_does_not_stop_other_sources(monkeypatch):
    quote = Quote(Decimal(100), Decimal(1), date(2026, 9, 18))

    async def empty_snapshots(session):
        return {}

    async def fetch_krx(client, indicator):
        return market.krx.MarketBatch(quote, [])

    async def fetch_fred(client, symbol):
        if symbol == "SP500":
            raise MarketDataError("NO_DATA")
        return quote

    class FakeKis:
        async def fetch_flow(self, kind):
            return []

        async def fetch_ranking(self, kind):
            return []

        async def fetch_quote(self):
            return quote

        async def fetch_gold_quote(self, symbol):
            return quote

    monkeypatch.setattr(market, "list_snapshots", empty_snapshots)
    monkeypatch.setattr(market, "list_rankings", empty_snapshots)
    monkeypatch.setattr(market.krx, "fetch_market", fetch_krx)
    monkeypatch.setattr(market.fred, "fetch_quote", fetch_fred)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            monkeypatch.setattr(market, "SessionLocal", factory)
            async with httpx.AsyncClient() as client:
                await market.collect(client, FakeKis())
            async with factory() as session:
                rows = {
                    row.code: row for row in (await session.scalars(select(MarketSnapshot))).all()
                }
                assert rows["sp500"].error_code == "NO_DATA"
                for code in ("kospi", "kosdaq", "nasdaq", "usdkrw", "gold"):
                    assert rows[code].error_code is None
                    assert rows[code].collected_at is not None
        finally:
            await transaction.rollback()


async def test_recent_snapshots_skip_every_upstream_call(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.schemas.ranking import ACTIVE_RANKINGS
    from app.services.market_data import INDICATORS

    now = datetime.now(UTC)

    async def snapshots(session):
        return {item.code: SimpleNamespace(checked_at=now) for item in INDICATORS}

    async def rankings(session):
        return {
            kind: SimpleNamespace(checked_at=now)
            for kind in (*ACTIVE_RANKINGS, *market.FLOW_KINDS, *market.SECTOR_CODES.values())
        }

    monkeypatch.setattr(market, "list_snapshots", snapshots)
    monkeypatch.setattr(market, "list_rankings", rankings)
    # 실제 HTTP client/키 없이도 만기가 안 된 데이터는 정상적으로 건너뛴다.
    delay = await market.collect(None, None)
    assert 55 < delay <= 60


async def test_slow_source_does_not_block_saving_other_results(monkeypatch):
    import asyncio

    quote = Quote(Decimal(100), Decimal(1), date(2026, 9, 18))
    saved = asyncio.Event()
    original_save = market.save_result

    async def empty(session):
        return {}

    async def fetch_krx(client, indicator):
        await asyncio.wait_for(saved.wait(), timeout=1)
        return market.krx.MarketBatch(quote, [])

    async def fetch_fred(client, symbol):
        return quote

    async def save(session, code, value, error, checked_at):
        await original_save(session, code, value, error, checked_at)
        if code == "usdkrw":
            saved.set()

    class FakeKis:
        async def fetch_flow(self, kind):
            return []

        async def fetch_quote(self):
            return quote

        async def fetch_gold_quote(self, symbol):
            return quote

        async def fetch_ranking(self, kind):
            return []

    monkeypatch.setattr(market, "list_snapshots", empty)
    monkeypatch.setattr(market, "list_rankings", empty)
    monkeypatch.setattr(market.krx, "fetch_market", fetch_krx)
    monkeypatch.setattr(market.fred, "fetch_quote", fetch_fred)
    monkeypatch.setattr(market, "save_result", save)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            monkeypatch.setattr(market, "SessionLocal", factory)
            await market.collect(None, FakeKis())
            async with factory() as session:
                row = await session.get(MarketSnapshot, "kospi")
                assert row.error_code is None
                assert saved.is_set()
        finally:
            await transaction.rollback()


async def test_sector_parse_failure_preserves_sector_but_updates_quote(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from app.models.ranking import RankingSnapshot
    from app.repositories.ranking import save_ranking
    from app.schemas.market_flow import SectorItem

    now = datetime.now(UTC)
    today = now.astimezone(ZoneInfo("Asia/Seoul")).date()
    quote = Quote(Decimal(7000), Decimal(2), today)

    async def snapshots(session):
        return {
            item.code: SimpleNamespace(checked_at=now)
            for item in market.INDICATORS
            if item.code != "kospi"
        }

    async def rankings(session):
        return {
            kind: SimpleNamespace(checked_at=now)
            for kind in (*market.ACTIVE_RANKINGS, *market.FLOW_KINDS, *market.SECTOR_CODES.values())
        }

    async def fetch_krx(client, indicator):
        return market.krx.MarketBatch(quote, None, sectors_error="INVALID_SECTORS")

    monkeypatch.setattr(market, "list_snapshots", snapshots)
    monkeypatch.setattr(market, "list_rankings", rankings)
    monkeypatch.setattr(market.krx, "fetch_market", fetch_krx)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            monkeypatch.setattr(market, "SessionLocal", factory)
            async with factory() as session:
                await save_ranking(
                    session,
                    "sectorKospi",
                    [SectorItem(name="건설", change=1, as_of=today)],
                    None,
                    now,
                )
                await session.commit()
            await market.collect(None, None)
            async with factory() as session:
                index = await session.get(MarketSnapshot, "kospi")
                sector = await session.get(RankingSnapshot, "sectorKospi")
                assert index.value == 7000
                assert index.error_code is None
                assert sector.items[0]["change"] == 1
                assert sector.error_code == "INVALID_SECTORS"
        finally:
            await transaction.rollback()


class _KisAllOk:
    async def fetch_flow(self, kind):
        return []

    async def fetch_ranking(self, kind):
        return []

    async def fetch_quote(self):
        return Quote(Decimal(100), Decimal(1), date(2026, 9, 18))

    async def fetch_gold_quote(self, symbol):
        return Quote(Decimal(100), Decimal(1), date(2026, 9, 18))


class _KisAllDown:
    async def fetch_flow(self, kind):
        raise MarketDataError("UPSTREAM_DOWN")

    async def fetch_ranking(self, kind):
        raise MarketDataError("UPSTREAM_DOWN")

    async def fetch_quote(self):
        raise MarketDataError("UPSTREAM_DOWN")

    async def fetch_gold_quote(self, symbol):
        raise MarketDataError("UPSTREAM_DOWN")


async def _run_collect(monkeypatch, kis, krx_batch, fred_fetch):
    """DB 는 트랜잭션 안에서만 쓰고 되돌린다. last-success 갱신 횟수를 돌려준다."""

    async def empty_snapshots(session):
        return {}

    async def fetch_krx(client, indicator):
        if isinstance(krx_batch, Exception):
            raise krx_batch
        return krx_batch

    touched = []
    monkeypatch.setattr(market, "list_snapshots", empty_snapshots)
    monkeypatch.setattr(market, "list_rankings", empty_snapshots)
    monkeypatch.setattr(market.krx, "fetch_market", fetch_krx)
    monkeypatch.setattr(market.fred, "fetch_quote", fred_fetch)
    monkeypatch.setattr(market, "touch_last_success", lambda: touched.append(1))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            factory = async_sessionmaker(
                connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            monkeypatch.setattr(market, "SessionLocal", factory)
            async with httpx.AsyncClient() as client:
                await market.collect(client, kis)
        finally:
            await transaction.rollback()
    return len(touched)


async def test_last_success_is_touched_once_when_sources_succeed(monkeypatch):
    quote = Quote(Decimal(100), Decimal(1), date(2026, 9, 18))

    async def fetch_fred(client, symbol):
        return quote

    count = await _run_collect(
        monkeypatch, _KisAllOk(), market.krx.MarketBatch(quote, []), fetch_fred
    )

    assert count == 1


async def test_last_success_is_touched_even_if_only_one_source_succeeds(monkeypatch):
    quote = Quote(Decimal(100), Decimal(1), date(2026, 9, 18))

    async def fetch_fred(client, symbol):
        raise MarketDataError("NO_DATA")

    count = await _run_collect(
        monkeypatch, _KisAllDown(), market.krx.MarketBatch(quote, [], None, "X"), fetch_fred
    )

    assert count == 1


async def test_last_success_is_not_touched_when_every_source_fails(monkeypatch):
    async def fetch_fred(client, symbol):
        raise MarketDataError("NO_DATA")

    count = await _run_collect(monkeypatch, _KisAllDown(), MarketDataError("NO_DATA"), fetch_fred)

    assert count == 0


async def test_last_success_is_not_touched_when_nothing_is_due(monkeypatch):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.schemas.ranking import ACTIVE_RANKINGS
    from app.services.market_data import INDICATORS

    now = datetime.now(UTC)
    touched = []

    async def snapshots(session):
        return {item.code: SimpleNamespace(checked_at=now) for item in INDICATORS}

    async def rankings(session):
        return {
            kind: SimpleNamespace(checked_at=now)
            for kind in (*ACTIVE_RANKINGS, *market.FLOW_KINDS, *market.SECTOR_CODES.values())
        }

    monkeypatch.setattr(market, "list_snapshots", snapshots)
    monkeypatch.setattr(market, "list_rankings", rankings)
    monkeypatch.setattr(market, "touch_last_success", lambda: touched.append(1))

    await market.collect(None, None)

    assert touched == []
