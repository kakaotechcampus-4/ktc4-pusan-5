"""uv run python -m app.collectors.market [--loop]

조회 서버와 분리된 단일 수집기. KIS 요청은 공유 클라이언트가 직렬화한다.
"""

import argparse
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.models  # noqa: F401
from app.collectors.stocks import StockWorker
from app.core.database import Base, SessionLocal, engine
from app.repositories.market import list_snapshots, save_result
from app.repositories.ranking import list_rankings, save_ranking
from app.schemas.market_flow import FLOW_KINDS, FlowItem
from app.schemas.ranking import ACTIVE_RANKINGS, RankingItem
from app.services import fred, krx
from app.services.kis import KisClient
from app.services.market_data import INDICATORS, MarketDataError, Quote

logger = logging.getLogger(__name__)
LOCK_ID = 4927105
FETCH_TIMEOUT = 25
Result = Quote | list[RankingItem] | list[FlowItem] | krx.MarketBatch
SECTOR_CODES = {"kospi": "sectorKospi", "kosdaq": "sectorKosdaq"}


async def fetch_result(code: str, fetch: Callable[[], Awaitable[Result]]):
    value, error = None, None
    try:
        async with asyncio.timeout(FETCH_TIMEOUT):
            value = await fetch()
    except MarketDataError as exc:
        error = str(exc)
    except httpx.HTTPStatusError as exc:
        error = f"UPSTREAM_HTTP_{exc.response.status_code}"
    except TimeoutError:
        error = "UPSTREAM_TIMEOUT"
    except (httpx.RequestError, ValueError, KeyError, TypeError, IndexError):
        error = "INVALID_OR_UNREACHABLE_UPSTREAM"
    return code, value, error


async def collect(client: httpx.AsyncClient, kis: KisClient) -> float:
    async with engine.connect() as lock_connection:
        locked = await lock_connection.scalar(text(f"SELECT pg_try_advisory_lock({LOCK_ID})"))
        if not locked:
            return 60
        tasks = []
        try:
            # 외부 통신 전에 일반 DB 세션을 닫는다. 락 전용 연결 하나만 유지한다.
            async with SessionLocal() as session:
                snapshots = await list_snapshots(session)
                rankings = await list_rankings(session)
            now = datetime.now(UTC)
            next_due = []
            jobs = []
            for indicator in INDICATORS:
                if not indicator.source:
                    continue
                row = snapshots.get(indicator.code)
                remaining = (
                    indicator.interval - (now - row.checked_at).total_seconds() if row else 0
                )
                if indicator.source == "KRX":
                    sector = rankings.get(SECTOR_CODES[indicator.code])
                    sector_remaining = (
                        indicator.interval - (now - sector.checked_at).total_seconds()
                        if sector
                        else 0
                    )
                    remaining = min(remaining, sector_remaining)
                next_due.append(max(0, remaining))
                if remaining > 0:
                    continue
                if indicator.source == "FRED":

                    async def fetch(indicator=indicator):
                        return await fred.fetch_quote(client, indicator.symbol)
                elif indicator.source == "KRX":

                    async def fetch(indicator=indicator):
                        return await krx.fetch_market(client, indicator)
                else:
                    fetch = kis.fetch_quote
                jobs.append((indicator.code, fetch, indicator.interval))
            for kind in (*ACTIVE_RANKINGS, *FLOW_KINDS):
                row = rankings.get(kind)
                remaining = 60 - (now - row.checked_at).total_seconds() if row else 0
                next_due.append(max(0, remaining))
                if remaining <= 0:

                    async def fetch(kind=kind):
                        return (
                            await kis.fetch_flow(kind)
                            if kind in FLOW_KINDS
                            else await kis.fetch_ranking(kind)
                        )

                    jobs.append((kind, fetch, 60))

            tasks = [asyncio.create_task(fetch_result(code, fetch)) for code, fetch, _ in jobs]
            # 느린 출처와 관계없이 완료된 항목부터 짧은 트랜잭션으로 저장한다.
            for completed in asyncio.as_completed(tasks):
                code, value, error = await completed
                async with SessionLocal() as session:
                    if code in SECTOR_CODES:
                        await save_result(
                            session,
                            code,
                            value.quote if value else None,
                            value.quote_error if value else error,
                            now,
                        )
                        await save_ranking(
                            session,
                            SECTOR_CODES[code],
                            value.sectors if value else None,
                            value.sectors_error if value else error,
                            now,
                        )
                    elif code in (*ACTIVE_RANKINGS, *FLOW_KINDS):
                        await save_ranking(session, code, value, error, now)
                    else:
                        await save_result(session, code, value, error, now)
                    await session.commit()
                if isinstance(value, krx.MarketBatch):
                    logger.info(
                        "%s: %s; sectors: %s",
                        code,
                        value.quote_error or "saved",
                        value.sectors_error or "saved",
                    )
                else:
                    logger.info("%s: %s", code, error or "saved")

            # 처리 시간을 더해 주기가 계속 밀리지 않게 다음 만기까지 기다린다.
            due = [remaining for remaining in next_due if remaining > 0]
            due.extend(interval for _, _, interval in jobs)
            elapsed = (datetime.now(UTC) - now).total_seconds()
            return max(1, min(due, default=60) - elapsed)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await lock_connection.execute(text(f"SELECT pg_advisory_unlock({LOCK_ID})"))
            await lock_connection.commit()


async def run(loop: bool) -> None:
    # 동일 계정의 홈/상세 KIS 호출이 프로세스별로 중복되지 않도록 워커 전체를 단일 리더로 운영.
    try:
        async with engine.connect() as leader:
            acquired = await leader.scalar(text("SELECT pg_try_advisory_lock(4927106)"))
            await leader.commit()
            if not acquired:
                logger.info("Another market worker is already running")
                return
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(
                        lambda sync: Base.metadata.create_all(
                            sync,
                            tables=[
                                t
                                for t in Base.metadata.sorted_tables
                                if not t.name.startswith("stock")
                                and t.name != "krx_historical_cache"
                            ],
                        )
                    )
                async with httpx.AsyncClient(timeout=15) as client:
                    kis = KisClient(client)
                    stocks = StockWorker(client, kis)
                    next_market = 0.0
                    while True:
                        try:
                            if time.monotonic() >= next_market:
                                delay = await collect(client, kis)
                                next_market = time.monotonic() + delay
                            if not loop:
                                break
                            await stocks.catalog()
                            # 홈 다음 수집 시각을 넘기지 않는 범위에서 상세 요청 한 건씩 수행한다.
                            budget = min(12, next_market - time.monotonic() - 1)
                            worked = await stocks.tick(timeout=budget) if budget >= 2 else False
                            if not worked:
                                await asyncio.sleep(
                                    min(1, max(0.1, next_market - time.monotonic()))
                                )
                        except (SQLAlchemyError, OSError) as exc:
                            logger.error("Market collection failed: %s", type(exc).__name__)
                            if not loop:
                                raise RuntimeError("Market collection failed") from None
                            await asyncio.sleep(5)
            finally:
                await leader.execute(text("SELECT pg_advisory_unlock(4927106)"))
                await leader.commit()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run(parser.parse_args().loop))
