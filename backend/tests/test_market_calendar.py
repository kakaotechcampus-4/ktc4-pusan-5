from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.market_calendar import TradingCalendar, last_market_close, market_open

KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = TradingCalendar({})  # 달력 행이 없으면 평일 기준


def kst(month, day, hour, minute, second=0):
    return datetime(2026, month, day, hour, minute, second, tzinfo=KST)


# 2026-10-05 는 월요일이다.
@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (kst(10, 5, 16, 0), kst(10, 5, 15, 40)),  # 월 장 마감 후 → 같은 날 마감
        (kst(10, 5, 10, 0), kst(10, 2, 15, 40)),  # 월 장중 → 직전 금요일 마감
        (kst(10, 5, 8, 0), kst(10, 2, 15, 40)),  # 월 개장 전 → 직전 금요일 마감
        (kst(10, 3, 12, 0), kst(10, 2, 15, 40)),  # 토 → 금요일 마감
        (kst(10, 4, 23, 0), kst(10, 2, 15, 40)),  # 일 → 금요일 마감
    ],
)
def test_last_market_close_without_rows_uses_weekdays(now, expected):
    assert last_market_close(now, WEEKDAYS) == expected


def test_weekday_holiday_is_not_open():
    # 2026-12-25 는 금요일이지만 휴장이다.
    calendar = TradingCalendar({date(2026, 12, 25): False})
    assert market_open(kst(12, 25, 10, 0), calendar) is False
    assert market_open(kst(12, 25, 10, 0), WEEKDAYS) is True
    assert market_open(kst(12, 24, 10, 0), calendar) is True


def test_last_close_skips_holiday():
    calendar = TradingCalendar({date(2026, 12, 25): False})
    # 토요일 기준 마지막 마감은 금요일(휴장)을 건너뛴 목요일 마감이다.
    assert last_market_close(kst(12, 26, 12, 0), calendar) == kst(12, 24, 15, 40)
    # 휴장일 당일 장 마감 시각 이후에도 오늘 마감으로 보지 않는다.
    assert last_market_close(kst(12, 25, 16, 0), calendar) == kst(12, 24, 15, 40)


def test_rows_override_only_their_days():
    # 다른 날짜 행만 있으면 그 날은 평일 기준이다.
    calendar = TradingCalendar({date(2026, 12, 25): False})
    assert last_market_close(kst(10, 5, 16, 0), calendar) == kst(10, 5, 15, 40)
    assert market_open(kst(10, 5, 10, 0), calendar) is True


def test_consecutive_holidays_are_skipped():
    # 2026 설 연휴: 2/16(월)~2/18(수) 휴장. 2/13(금)이 마지막 거래일이다.
    calendar = TradingCalendar(
        {date(2026, 2, 16): False, date(2026, 2, 17): False, date(2026, 2, 18): False}
    )
    assert last_market_close(kst(2, 18, 12, 0), calendar) == kst(2, 13, 15, 40)
    assert last_market_close(kst(2, 19, 10, 0), calendar) == kst(2, 13, 15, 40)
    assert last_market_close(kst(2, 19, 16, 0), calendar) == kst(2, 19, 15, 40)
    assert market_open(kst(2, 17, 10, 0), calendar) is False


def test_month_of_closed_rows_falls_back_to_weekdays():
    # 저장 값이 잘못돼 한 달 넘게 휴장이라고 해도 끝없이 거슬러 가지 않는다.
    calendar = TradingCalendar(
        {date(2026, 8, 1) + timedelta(days=offset): False for offset in range(61)}
    )
    assert last_market_close(kst(9, 30, 16, 0), calendar) == kst(9, 29, 15, 40)
