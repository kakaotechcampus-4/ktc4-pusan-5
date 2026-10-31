"""저장된 시세가 낡았는지 판단한다. 외부 호출은 하지 않는다."""

from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.core.config import settings

KST = ZoneInfo("Asia/Seoul")
# market_open 의 마감 시각(15:40)과 같다.
MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 40
# 장중 갱신 주기. 수집기의 현재가 수집 주기와 같은 값
SNAPSHOT_TTL = settings.stock_quote_interval_seconds

QuoteStatus = Literal["ready", "stale", "pending"]


def market_open(now: datetime) -> bool:
    local = now.astimezone(KST)
    return local.weekday() < 5 and (9, 0) <= (local.hour, local.minute) < (
        MARKET_CLOSE_HOUR,
        MARKET_CLOSE_MINUTE,
    )


def last_market_close(now: datetime) -> datetime:
    """가장 최근에 장이 마감한 시각. 휴장일 달력은 아직 없어서 평일만 본다."""
    local = now.astimezone(KST)
    close = local.replace(
        hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0
    )
    if local.weekday() >= 5 or local < close:
        close -= timedelta(days=1)
        while close.weekday() >= 5:
            close -= timedelta(days=1)
    return close


def is_quote_stale(collected_at: datetime, now: datetime) -> bool:
    """장중에는 갱신 주기(SNAPSHOT_TTL)가 지났는지, 장외에는 마지막 마감 이후에 받은 값인지로 본다.

    마감 시세는 다음 개장 전까지 최신이다. 수집기도 같은 기준으로 다시 받을지 정하므로
    장외에는 마감 후 한 번만 수집한다.
    """
    if market_open(now):
        return (now - collected_at).total_seconds() >= SNAPSHOT_TTL
    return collected_at < last_market_close(now)


def quote_status(collected_at: datetime | None, now: datetime) -> QuoteStatus:
    if collected_at is None:
        return "pending"
    return "stale" if is_quote_stale(collected_at, now) else "ready"
