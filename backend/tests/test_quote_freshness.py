from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.quote_freshness import is_quote_stale, last_market_close, quote_status

KST = ZoneInfo("Asia/Seoul")


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
def test_last_market_close(now, expected):
    assert last_market_close(now) == expected


@pytest.mark.parametrize(
    ("now", "collected_at", "stale"),
    [
        # 장중(월 10:00)에는 60초가 지나면 낡았다
        (kst(10, 5, 10, 0), kst(10, 5, 9, 59, 1), False),  # 59초 전
        (kst(10, 5, 10, 0), kst(10, 5, 9, 59, 0), True),  # 정확히 60초 전(상세 화면과 같은 기준)
        (kst(10, 5, 10, 0), kst(10, 2, 15, 50), True),  # 지난 금요일 값
        # 장 마감 후(월 16:00): 오늘 마감 이후에 받은 값이면 최신
        (kst(10, 5, 16, 0), kst(10, 5, 15, 45), False),
        (kst(10, 5, 16, 0), kst(10, 5, 14, 0), True),  # 마감 전 장중 값
        # 주말(토 12:00): 금요일 마감 이후에 받은 값이면 최신
        (kst(10, 3, 12, 0), kst(10, 2, 15, 50), False),
        (kst(10, 3, 12, 0), kst(10, 2, 15, 0), True),
        (kst(10, 3, 12, 0), kst(10, 1, 15, 50), True),  # 목요일 값
        # 개장 전(월 08:00): 금요일 마감 이후에 받은 값이면 최신
        (kst(10, 5, 8, 0), kst(10, 2, 15, 50), False),
    ],
)
def test_is_quote_stale(now, collected_at, stale):
    assert is_quote_stale(collected_at, now) is stale


def test_quote_status():
    now = kst(10, 5, 16, 0)
    assert quote_status(None, now) == "pending"
    assert quote_status(kst(10, 5, 15, 45), now) == "ready"
    assert quote_status(kst(10, 5, 14, 0), now) == "stale"
