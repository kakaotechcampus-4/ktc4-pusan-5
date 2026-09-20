"""시장 수집기의 KIS 클라이언트를 공유하는 종목 작업 처리기."""

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.models.stock import Stock, StockCollectionState
from app.repositories import stock as repo
from app.repositories.stock_financials import save_periods
from app.schemas.stock import MetricsData, QuoteData
from app.services import stock_data, stock_financials
from app.services.market_data import MarketDataError
from app.services.stock_detail import ACTIVE_WINDOW, snapshot_ttl

logger = logging.getLogger(__name__)


class StockWorker:
    def __init__(self, client: httpx.AsyncClient, kis):
        self.client = client
        self.kis = kis
        self.catalog_retry_at = datetime.min.replace(tzinfo=UTC)
        self.active_checked_at = datetime.min.replace(tzinfo=UTC)

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

    async def schedule_active(self):
        now = datetime.now(UTC)
        if now - self.active_checked_at < timedelta(seconds=15):
            return
        self.active_checked_at = now
        async with SessionLocal() as session:
            states = (
                await session.scalars(
                    select(StockCollectionState)
                    .join(Stock, Stock.code == StockCollectionState.stock_code)
                    .where(
                        StockCollectionState.resource == "snapshot",
                        Stock.listing_status == "listed",
                        StockCollectionState.last_requested_at > now - ACTIVE_WINDOW,
                    )
                )
            ).all()
            for state in states:
                if not state.last_success_at or (
                    now - state.last_success_at
                ).total_seconds() >= snapshot_ttl(now):
                    await repo.enqueue(session, state.stock_code, "snapshot", now, priority=0)
            await session.commit()

    async def tick(self, timeout: float = 12):
        await self.schedule_active()
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
                elif job.resource in ("income", "eps", "stability"):
                    fetch = {
                        "income": stock_financials.fetch_income,
                        "eps": stock_financials.fetch_eps,
                        "stability": stock_financials.fetch_stability,
                    }[job.resource]
                    value = await fetch(self.kis, job.stock_code)
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
            elif not error and job.resource in ("income", "eps", "stability"):
                error = await save_periods(
                    session, job.stock_code, job.resource, [asdict(row) for row in value], now
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
