"""uv run python -m app.collectors.market [--loop]

조회 서버와 분리된 단일 수집기. KIS 요청은 공유 클라이언트가 직렬화한다.
"""

import argparse
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

import app.models  # noqa: F401
from app.collectors.stocks import StockWorker
from app.core.database import SessionLocal, engine, ensure_schema_current
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
# 루프가 DB 오류 없이 한 바퀴 돌 때마다 이 파일의 수정 시각을 갱신한다. docker compose 헬스체크가 이 시각을 본다.
# "수집기 프로세스와 루프가 살아 있음"(liveness)만 뜻한다. KIS/KRX/FRED 오류는 fetch_result 가 결과값으로
# 흡수하므로, 외부 소스가 계속 실패해도 이 파일은 갱신된다. 실제 수집 성공 여부는 아래 LAST_SUCCESS_PATH 를 본다.
HEARTBEAT_PATH = Path("/tmp/collector-heartbeat")
# 홈 시장 데이터가 한 건이라도 오류 없이 수집·저장됐을 때 갱신한다. 헬스체크는 보지 않고, 사람이 확인하는 용도다.
#   docker compose exec collector stat -c '%y' /tmp/collector-last-success
# 수집할 만기가 없던 반복에서는 갱신하지 않으므로, 오래됐다는 것만으로 이상이라고 단정하지 않는다.
LAST_SUCCESS_PATH = Path("/tmp/collector-last-success")


def _touch(path: Path, label: str) -> None:
    try:
        path.touch()
    except OSError:
        logger.warning("%s: cannot write %s", label, path)


def touch_heartbeat(path: Path = HEARTBEAT_PATH) -> None:
    """루프가 한 바퀴 끝까지 돌았다는 표시. 쓰지 못해도 수집을 멈추지 않는다(헬스체크만 실패한다)."""
    _touch(path, "heartbeat")


def touch_last_success(path: Path = LAST_SUCCESS_PATH) -> None:
    """마지막으로 수집에 성공한 시각 표시. 쓰지 못해도 수집을 멈추지 않는다."""
    _touch(path, "last-success")


def is_success(value: object, error: str | None) -> bool:
    """fetch_result 의 결과가 성공인지. KRX 묶음은 지수나 업종 중 하나만 얻어도 성공으로 본다."""
    if isinstance(value, krx.MarketBatch):
        return value.quote_error is None or value.sectors_error is None
    return value is not None and error is None


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
                elif indicator.code == "gold":

                    async def fetch(indicator=indicator):
                        return await kis.fetch_gold_quote(indicator.symbol)
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
            any_success = False
            # 느린 출처와 관계없이 완료된 항목부터 짧은 트랜잭션으로 저장한다.
            for completed in asyncio.as_completed(tasks):
                code, value, error = await completed
                any_success = any_success or is_success(value, error)
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

            # 저장까지 끝난 뒤 한 번만 갱신한다. 한 건도 성공하지 못했거나 수집할 항목이 없었으면 건드리지 않는다.
            if any_success:
                touch_last_success()

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
                # `uv run alembic upgrade head` 로 db 최신상태로 맞춰두기
                await ensure_schema_current()
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
                            # DB 오류 없이 한 바퀴를 돌았을 때만 갱신한다. 루프가 멈추거나 DB 오류가 계속 나면 갱신이 끊겨
                            # 헬스체크가 실패한다. 외부 소스(KIS 등) 오류는 흡수돼 여기에 영향이 없다(LAST_SUCCESS_PATH 참고).
                            touch_heartbeat()
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
