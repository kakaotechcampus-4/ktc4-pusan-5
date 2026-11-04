"""저장된 시세가 낡았는지 판단한다. 외부 호출은 하지 않는다."""

from datetime import datetime
from typing import Literal

from app.core.config import settings
from app.services.market_calendar import TradingCalendar, last_market_close, market_open

# 장중 갱신 주기. 수집기의 현재가 수집 주기와 같은 값
SNAPSHOT_TTL = settings.stock_quote_interval_seconds

QuoteStatus = Literal["ready", "stale", "pending"]


def is_quote_stale(collected_at: datetime, now: datetime, calendar: TradingCalendar) -> bool:
    """장중에는 갱신 주기(SNAPSHOT_TTL)가 지났는지, 장외에는 마지막 마감 이후에 받은 값인지로 본다.

    마감 시세는 다음 개장 전까지 최신이다. 수집기도 같은 기준으로 다시 받을지 정하므로
    장외에는 마감 후 한 번만 수집한다. 휴장일은 calendar 로 판단한다.
    """
    if market_open(now, calendar):
        return (now - collected_at).total_seconds() >= SNAPSHOT_TTL
    return collected_at < last_market_close(now, calendar)


def quote_status(
    collected_at: datetime | None, now: datetime, calendar: TradingCalendar
) -> QuoteStatus:
    if collected_at is None:
        return "pending"
    return "stale" if is_quote_stale(collected_at, now, calendar) else "ready"
