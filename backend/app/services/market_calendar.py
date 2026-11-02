"""장 운영 시간과 휴장일 판단. 외부 호출은 하지 않는다.

휴장일은 수집기가 KIS 국내휴장일조회로 받아 market_calendar 에 저장한 값을 호출부가 읽어 넘긴다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
# market_open 의 마감 시각(15:40)
MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 40
# 마지막 개장일을 찾아 거슬러 올라가는 최대 일수. 설·추석 연휴보다 충분히 길다.
MAX_LOOKBACK_DAYS = 30


@dataclass(frozen=True)
class TradingCalendar:
    days: Mapping[date, bool]  # market_calendar 에서 읽은 날짜별 개장 여부

    def is_open_day(self, day: date) -> bool:
        # 행이 없으면 평일을 개장일로 봄. KIS 조회 실패·배포 직후·테이블 이전 과거 날짜에서 장 열렸는데 휴장일로 판단하면 수집기 멈추기 때문
        if day in self.days:
            return self.days[day]
        return day.weekday() < 5


def market_open(now: datetime, calendar: TradingCalendar) -> bool:
    local = now.astimezone(KST)
    return calendar.is_open_day(local.date()) and (9, 0) <= (
        local.hour,
        local.minute,
    ) < (
        MARKET_CLOSE_HOUR,
        MARKET_CLOSE_MINUTE,
    )


def last_market_close(now: datetime, calendar: TradingCalendar) -> datetime:
    """가장 최근에 장이 마감한 시각. 휴장일은 건너뛴다."""
    local = now.astimezone(KST)
    day = local.date()
    if not calendar.is_open_day(day) or (local.hour, local.minute) < (
        MARKET_CLOSE_HOUR,
        MARKET_CLOSE_MINUTE,
    ):
        day = _previous_open_day(day, calendar)
    return datetime.combine(
        day, time(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE), tzinfo=KST
    )


def _previous_open_day(day: date, calendar: TradingCalendar) -> date:
    for offset in range(1, MAX_LOOKBACK_DAYS + 1):
        candidate = day - timedelta(days=offset)
        if calendar.is_open_day(candidate):
            return candidate
    # 한 달 내내 휴장이라는 달력은 저장 값이 오류임, 평일 기준으로 돌아가 마지막 마감을 너무 과거로 잡지 않게 함
    return _previous_open_day(day, TradingCalendar({}))
