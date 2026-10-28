"""시장 수집기의 KIS 클라이언트를 공유하는 종목 작업 처리기."""

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.core.mvp_stocks import MVP_CODES
from app.models.stock import Stock, StockCollectionState
from app.repositories import stock as repo
from app.repositories.stock_financials import save_periods
from app.repositories.stock_history import save_history
from app.schemas.stock import MetricsData, QuoteData
from app.services import stock_data, stock_financials, stock_history
from app.services.krx_history import krx_rows
from app.services.market_data import MarketDataError
from app.services.quote_freshness import is_quote_stale

logger = logging.getLogger(__name__)


async def schedule(session, code, resource, now, priority):
    """정기 수집 작업은 이 함수로만 등록한다.

    repo.finish() 는 stock_collection_state 행을 UPDATE 만 하므로 행이 없으면 성공 시각이 남지 않고,
    다음 확인 때 또 만기로 보여 계속 다시 등록된다. touch() 로 행을 먼저 만든다.
    이때 last_requested_at 은 사용자 조회 시각이 아니라 수집기가 등록한 시각이다.
    """
    await repo.touch(session, code, resource, now)
    await repo.enqueue(session, code, resource, now, priority=priority)


class StockWorker:
    def __init__(self, client: httpx.AsyncClient, kis):
        self.client = client
        self.kis = kis
        self.catalog_retry_at = datetime.min.replace(tzinfo=UTC)
        self.snapshot_checked_at = datetime.min.replace(tzinfo=UTC)

    async def catalog(self):
        now = datetime.now(UTC)
        if now < self.catalog_retry_at:
            return
        async with SessionLocal() as session:
            checked = await repo.catalog_checked_at(session)
        if checked and now - checked < timedelta(days=1):
            self.catalog_retry_at = checked + timedelta(days=1)
            return
        self.catalog_retry_at = now + timedelta(minutes=10)
        try:
            async with asyncio.timeout(25):
                rows = await stock_data.fetch_catalog(self.client)
            async with SessionLocal() as session:
                await repo.sync_catalog(session, [asdict(row) for row in rows], now)
                await session.commit()
            self.catalog_retry_at = now + timedelta(days=1)
            logger.info("stock catalog: %d saved", len(rows))
        except (MarketDataError, httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            logger.warning("stock catalog: refresh failed; previous catalog retained")

    async def schedule_snapshots(self):
        # 사용자 조회와 무관하게 고정 목록 전체의 현재가를 갱신 기준이 지난 것만 넣는다.
        # 종목마다 성공 시각이 달라 다음 만기도 흩어지므로 한 번에 몰리지 않는다.
        now = datetime.now(UTC)
        if now - self.snapshot_checked_at < timedelta(seconds=15):
            return
        self.snapshot_checked_at = now
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(Stock.code, StockCollectionState.last_success_at)
                    .outerjoin(
                        StockCollectionState,
                        and_(
                            StockCollectionState.stock_code == Stock.code,
                            StockCollectionState.resource == "snapshot",
                        ),
                    )
                    .where(Stock.code.in_(MVP_CODES), Stock.listing_status == "listed")
                )
            ).all()
            for code, last_success_at in rows:
                if last_success_at is None or is_quote_stale(last_success_at, now):
                    await schedule(session, code, "snapshot", now, priority=0)
            await session.commit()

    async def tick(self, timeout: float = 12):
        await self.schedule_snapshots()
        async with SessionLocal() as session:
            job = await repo.claim(session, datetime.now(UTC))
            await session.commit()
        if job is None:
            return False
        value, error = None, None
        try:
            async with asyncio.timeout(timeout):
                if job.resource == "snapshot":
                    value = await stock_data.fetch_snapshot(self.kis, job.stock_code)
                    # DB에 넣기 전에 HTTP 계약의 허용 범위도 확인한다.
                    if value.quote is not None:
                        QuoteData.model_validate(value.quote)
                    if value.metrics is not None:
                        MetricsData.model_validate(value.metrics)
                elif job.resource in (
                    "income",
                    "eps",
                    "stability",
                    "quarter_income",
                    "quarter_ratios",
                ):
                    fetch = {
                        "income": stock_financials.fetch_income,
                        "eps": stock_financials.fetch_eps,
                        "stability": stock_financials.fetch_stability,
                        "quarter_income": stock_financials.fetch_quarterly_income,
                        "quarter_ratios": stock_financials.fetch_quarterly_ratios,
                    }[job.resource]
                    value = await fetch(self.kis, job.stock_code)
                elif job.resource in ("history_cap", "history_rs"):
                    async with SessionLocal() as lookup:
                        stock = await lookup.get(Stock, job.stock_code)
                        market = stock.market

                    async def cached_rows(market, kind, day):
                        return await krx_rows(self.client, market, kind, day)

                    if job.resource == "history_cap":
                        value = await stock_history.fetch_cap(
                            self.client, job.stock_code, market, job.range_start, cached_rows
                        )
                    else:
                        value = await stock_history.fetch_rs(
                            self.kis, job.stock_code, market, job.range_start, cached_rows
                        )
                elif job.resource == "prices":
                    value = await stock_data.fetch_prices(
                        self.kis, job.stock_code, job.range_start, job.range_end
                    )
        except MarketDataError as exc:
            error = str(exc)
        except httpx.HTTPStatusError as exc:
            error = f"UPSTREAM_HTTP_{exc.response.status_code}"
        except TimeoutError:
            error = "UPSTREAM_TIMEOUT"
        except (httpx.RequestError, ValueError, KeyError, TypeError, IndexError):
            error = "INVALID_RESPONSE"
        if error:
            value = None
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            owned = await repo.owned_job(session, job.id, job.lease_token, now)
            if not owned:
                return True
            if not error and job.resource == "snapshot":
                rejected = await repo.save_snapshot(
                    session, job.stock_code, value.quote, value.metrics, now
                )
                for resource, data, failure in (
                    ("quote", value.quote, value.quote_error),
                    ("metrics", value.metrics, value.metrics_error),
                ):
                    if resource in rejected:
                        failure = "OUTDATED_RESPONSE"
                    await self._state(
                        session,
                        job.stock_code,
                        resource,
                        failure,
                        data is not None and not failure,
                        now,
                    )
                error = (
                    value.quote_error
                    or value.metrics_error
                    or ("OUTDATED_RESPONSE" if rejected else None)
                )
            elif not error and job.resource in (
                "income",
                "eps",
                "stability",
                "quarter_income",
                "quarter_ratios",
            ):
                error = await save_periods(
                    session, job.stock_code, job.resource, [asdict(row) for row in value], now
                )
            elif not error and job.resource in ("history_cap", "history_rs"):
                await save_history(
                    session, job.stock_code, job.range_start, job.resource, value, now
                )
            elif not error:
                await repo.save_prices(session, job, [asdict(row) for row in value], now)
            if error and job.resource == "snapshot" and value is None:
                for resource in ("quote", "metrics"):
                    await self._state(session, job.stock_code, resource, error, False, now)
            await repo.finish(session, owned, error, now)
            await session.commit()
        logger.info("stock %s %s: %s", job.stock_code, job.resource, error or "saved")
        return True

    @staticmethod
    async def _state(session, code, resource, error, success, now):
        values = {
            "stock_code": code,
            "resource": resource,
            "last_requested_at": now,
            "last_attempt_at": now,
            "error_code": error,
            "next_retry_at": now + timedelta(seconds=30) if error else None,
        }
        if success:
            values["last_success_at"] = now
        statement = insert(StockCollectionState).values(**values)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["stock_code", "resource"],
                set_={
                    key: statement.excluded[key]
                    for key in values
                    if key not in ("stock_code", "resource", "last_requested_at")
                },
            )
        )
