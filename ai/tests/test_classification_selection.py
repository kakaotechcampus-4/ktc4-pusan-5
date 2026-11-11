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
    same_story,
    title_words,
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
    # 제목은 서로 다른 소식이어야 한다(낱말이 겹치면 같은 소식으로 묶인다)
    candidates = [
        news(1, "D램 가격 반등", "삼성전자", hour=10),
        news(2, "파운드리 수주 경쟁", "삼성전자 삼전", hour=9),
        news(3, "가전 판매 부진", "삼성전자", hour=11),
    ]
    # 본문 언급 2회인 2 가 먼저, 같은 1회끼리는 최신(3)이 먼저
    assert rank_news(candidates, [MOCK_SAMSUNG], cap=3) == {2: 0, 3: 1, 1: 2}


def test_promotional_title_goes_behind_ordinary_news():
    candidates = [
        news(1, "삼성전자, 사회공헌 봉사활동 진행", "삼성전자 삼성전자 삼성전자", hour=11),
        news(2, "반도체 업황 점검", "삼성전자"),
    ]
    # 홍보 기사는 제목에 이름이 있고 더 최신이어도, 제목에 이름이 없는 일반 기사보다 뒤다
    assert rank_news(candidates, [MOCK_SAMSUNG], cap=1) == {2: 0}


def test_promotional_news_is_still_picked_when_there_is_room():
    candidates = [news(1, "삼성전자, 올해의 브랜드상 수상"), news(2, "삼성전자 실적")]
    # 빼는 것이 아니라 내리는 것이다. 자리가 남으면 분류한다
    assert rank_news(candidates, [MOCK_SAMSUNG], cap=2) == {2: 0, 1: 1}


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


def test_similar_titles_count_as_one_story_and_free_the_slot():
    candidates = [
        news(1, "삼성전자, 천장형 디지털 엑스레이 'GC85A Fit' 출시", hour=11),
        news(2, "삼성전자, 천장형 디지털 엑스레이 신제품 출시", hour=10),
        news(3, "삼성전자, 3분기 영업이익 12조", hour=9),
    ]
    # 2 는 1 과 낱말이 많이 겹쳐 같은 소식이다. 그 자리는 다른 소식인 3 이 받는다(11-09 실제 제목)
    assert same_story(title_words(candidates[0].title, ("삼성전자",)),
                      title_words(candidates[1].title, ("삼성전자",)))
    assert rank_news(candidates, [MOCK_SAMSUNG], cap=2) == {1: 0, 3: 1}


def test_title_words_drop_stock_names_brackets_and_one_particle():
    words = title_words("[단독] 삼성물산, 목동13단지 재건축을 수주", ("삼성물산",))
    assert words == frozenset({"목동13단지", "재건축", "수주"})


def test_price_words_keep_their_last_letter():
    # 신고가의 '가' 를 조사로 떼면 '신고' 가 되어 공정위 신고 기사와 같은 소식이 된다(#113 리뷰)
    assert "신고가" in title_words("SK하이닉스 신고가 경신", ("SK하이닉스",))
    candidates = [news(1, "SK하이닉스 신고가 경신", hour=9), news(2, "SK하이닉스 공정위 신고 접수", hour=8)]
    assert rank_news(candidates, [MOCK_HYNIX], cap=2) == {1: 0, 2: 1}


def test_stock_name_alone_does_not_make_titles_the_same_story():
    # 종목 이름을 빼고 비교하므로 '삼성전자' 만 같은 제목은 다른 소식이다
    candidates = [news(1, "삼성전자 노조 파업", hour=9), news(2, "삼성전자 HBM 공급 계약", hour=8)]
    assert rank_news(candidates, [MOCK_SAMSUNG], cap=2) == {1: 0, 2: 1}


def test_one_common_word_does_not_make_titles_the_same_story():
    # '검토' 하나만 겹치면 1/2 = 0.5 라도 다른 소식이다(#113 리뷰)
    candidates = [news(1, "현대차 리콜 검토", hour=9), news(2, "현대차 노조 파업 검토", hour=8)]
    assert rank_news(candidates, [Stock(code="005380", name="현대차", aliases=(), subsidiaries=())], cap=2) \
        == {1: 0, 2: 1}


def test_one_word_title_still_matches_on_that_word():
    assert same_story(frozenset({"LS그룹"}), frozenset({"LS그룹", "임원인사", "단행"}))


def test_titles_without_words_are_not_the_same_story():
    assert not same_story(frozenset(), frozenset({"실적"}))
    assert not same_story(frozenset(), frozenset())


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
