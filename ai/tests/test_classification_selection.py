"""분류할 자료 고르기: 네이버 뉴스 종목당 상한과 하루 비용 상한 (DB 없음)."""

from datetime import UTC, date, datetime

import pytest

from app.services.classification.basis import Stock
from app.services.classification.selection import (
    DailyBudget,
    NewsCandidate,
    normalize_title,
    order_for_classification,
    rank_news,
)

MOCK_SAMSUNG = Stock(code="005930", name="삼성전자", aliases=("삼전",), subsidiaries=("삼성디스플레이",))
MOCK_HYNIX = Stock(code="000660", name="SK하이닉스", aliases=(), subsidiaries=())
STOCKS = [MOCK_SAMSUNG, MOCK_HYNIX]
DAY = date(2026, 11, 6)


def news(card_id: int, title: str, body: str = "", *, day: date = DAY, hour: int = 9) -> NewsCandidate:
    return NewsCandidate(card_id=card_id, day=day, title=title, body=body,
                         published_at=datetime(day.year, day.month, day.day, hour, tzinfo=UTC))


def test_title_mention_ranks_above_body_mentions():
    candidates = [
        news(1, "반도체 업황 점검", "삼성전자 삼성전자 삼성전자"),
        news(2, "삼성전자, 신제품 공개", "본문"),
    ]
    assert rank_news(candidates, [MOCK_SAMSUNG], cap=1) == {2: 0}


def test_body_count_then_recency_break_ties():
    candidates = [
        news(1, "업황", "삼성전자", hour=10),
        news(2, "업황 둘", "삼성전자 삼전", hour=9),
        news(3, "업황 셋", "삼성전자", hour=11),
    ]
    # 본문 언급 2회인 2 가 먼저, 같은 1회끼리는 최신(3)이 먼저
    assert rank_news(candidates, [MOCK_SAMSUNG], cap=3) == {2: 0, 3: 1, 1: 2}


def test_aliases_and_subsidiaries_count_as_mentions():
    candidates = [news(1, "삼성디스플레이 OLED 투자"), news(2, "날씨", "맑음")]
    assert rank_news(candidates, STOCKS, cap=5) == {1: 0}


def test_same_title_from_other_publishers_counts_once():
    candidates = [
        news(1, "[속보] 삼성전자, 자사주 소각", hour=9),
        news(2, "삼성전자 자사주 소각 (종합)", hour=10),
        news(3, "삼성전자, 3분기 실적", hour=8),
    ]
    # 1·2 는 정규화하면 같은 제목. 최신인 2 만 남고 다음 자리는 3 이 받는다
    assert normalize_title(candidates[0].title) == normalize_title(candidates[1].title)
    assert rank_news(candidates, [MOCK_SAMSUNG], cap=2) == {2: 0, 3: 1}


def test_cap_is_per_stock_and_per_day_and_union_keeps_best_rank():
    candidates = [
        news(1, "삼성전자·SK하이닉스 동반 급락"),
        news(2, "SK하이닉스 HBM 공급"),
        news(3, "삼성전자 파운드리"),
        news(4, "삼성전자 배당", day=date(2026, 11, 5)),
    ]
    picked = rank_news(candidates, STOCKS, cap=1)
    # 11-06: 삼성전자 1위는 카드 3(id 큰 것), SK하이닉스 1위는 카드 2. 11-05 는 따로 센다
    assert picked == {3: 0, 2: 0, 4: 0}


def test_cap_must_be_positive():
    with pytest.raises(ValueError, match="1 이상"):
        rank_news([], STOCKS, cap=0)


def test_order_puts_other_sources_first_then_naver_by_rank_and_drops_the_rest():
    naver = [news(10, "삼성전자 실적", hour=9), news(11, "삼성전자 노조", hour=8),
             news(12, "삼성전자 행사", hour=7)]
    # 후보 순서는 최근 순(cards_to_classify). 20·21 은 텔레그램·PDF
    card_ids = [12, 20, 11, 21, 10]
    ordered, dropped = order_for_classification(card_ids, naver, STOCKS, cap=2)
    assert ordered == [20, 21, 10, 11]
    assert dropped == 1


def test_already_classified_news_still_takes_its_rank():
    # 10 은 이미 분류해서 후보에 없지만 그날 1위다. 상한 1 이면 남은 자리가 없다
    naver = [news(10, "삼성전자 실적", hour=9), news(11, "삼성전자 노조", hour=8)]
    ordered, dropped = order_for_classification([11], naver, STOCKS, cap=1)
    assert ordered == []
    assert dropped == 1


def test_daily_budget_stops_after_limit():
    budget = DailyBudget(limit=10.0, spent=8.0)
    assert budget.allows()
    budget.add(2.5)
    assert not budget.allows()


def test_no_daily_budget_always_allows():
    budget = DailyBudget(limit=None, spent=1e9)
    assert budget.allows()
